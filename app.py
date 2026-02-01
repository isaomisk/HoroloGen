from flask import Flask, render_template, request, redirect, url_for, flash
import json
import csv
import io
import os
import sqlite3

from models import init_db, get_db_connection, REQUIRED_CSV_COLUMNS
import llm_client as llmc

app = Flask(__name__)
init_db()
app.secret_key = 'horologen-secret-key-change-in-production'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

BRANDS = ['cartier', 'omega', 'grand_seiko', 'iwc', 'panerai']


@app.route('/')
def index():
    return redirect(url_for('admin_upload'))


@app.route('/admin/upload', methods=['GET', 'POST'])
def admin_upload():
    if request.method == 'POST':
        file = request.files.get('csv_file')

        if not file or file.filename == '':
            flash('ファイルが選択されていません', 'error')
            return redirect(url_for('admin_upload'))

        if not file.filename.endswith('.csv'):
            flash('CSVファイルを選択してください', 'error')
            return redirect(url_for('admin_upload'))

        conn = None
        try:
            raw = file.read()
            text = raw.decode('utf-8-sig')
            stream = io.StringIO(text)
            reader = csv.DictReader(stream)

            csv_columns = reader.fieldnames
            if csv_columns is None:
                flash('CSVファイルが空です', 'error')
                return redirect(url_for('admin_upload'))

            csv_columns = [col.strip() for col in csv_columns]

            missing_columns = set(REQUIRED_CSV_COLUMNS) - set(csv_columns)
            if missing_columns:
                flash(f'必須カラムが不足しています: {", ".join(sorted(missing_columns))}', 'error')
                return redirect(url_for('admin_upload'))

            extra_columns = set(csv_columns) - set(REQUIRED_CSV_COLUMNS)
            if extra_columns:
                flash(f'不正なカラムが含まれています: {", ".join(sorted(extra_columns))}。インポートを停止します。', 'error')
                return redirect(url_for('admin_upload'))

            conn = get_db_connection()
            cursor = conn.cursor()

            total_rows = 0
            inserted_count = 0
            updated_count = 0
            error_count = 0
            error_details = []
            changed_count = 0
            override_conflict_count = 0
            sample_diffs = []

            fields = [
                'price_jpy', 'case_size_mm', 'movement', 'case_material',
                'bracelet_strap', 'dial_color', 'water_resistance_m', 'buckle',
                'warranty_years', 'collection', 'movement_caliber',
                'case_thickness_mm', 'lug_width_mm', 'remarks'
            ]

            for row_num, row in enumerate(reader, start=2):
                total_rows += 1
                row = {k.strip(): (v.strip() if v else '') for k, v in row.items()}

                brand = row.get('brand', '').strip()
                reference = row.get('reference', '').strip()

                if not brand or not reference:
                    error_count += 1
                    error_details.append(f'行{row_num}: brandまたはreferenceが空です')
                    continue

                data = {f: row.get(f, '') for f in fields}
                data['brand'] = brand
                data['reference'] = reference

                try:
                    cursor.execute(
                        "SELECT * FROM master_products WHERE brand = ? AND reference = ?",
                        (brand, reference)
                    )
                    existing = cursor.fetchone()

                    cursor.execute(
                        "SELECT 1 FROM product_overrides WHERE brand = ? AND reference = ?",
                        (brand, reference)
                    )
                    override_exists = cursor.fetchone() is not None

                    row_changed = False
                    row_has_override_conflict = False
                    row_diffs = []

                    if existing:
                        for f in fields:
                            old_value = existing[f] or ''
                            new_value = data[f] or ''
                            if old_value != new_value:
                                row_changed = True
                                diff_info = {'field': f, 'old': old_value, 'new': new_value}
                                if override_exists:
                                    row_has_override_conflict = True
                                    diff_info['override_exists'] = True
                                row_diffs.append(diff_info)

                        if row_changed:
                            changed_count += 1
                            if row_has_override_conflict:
                                override_conflict_count += 1
                            if len(sample_diffs) < 10:
                                sample_diffs.append({
                                    'brand': brand,
                                    'reference': reference,
                                    'diffs': row_diffs
                                })

                    cursor.execute('''
                        INSERT INTO master_products
                        (brand, reference, price_jpy, case_size_mm, movement, case_material,
                         bracelet_strap, dial_color, water_resistance_m, buckle, warranty_years,
                         collection, movement_caliber, case_thickness_mm, lug_width_mm, remarks, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(brand, reference) DO UPDATE SET
                            price_jpy = excluded.price_jpy,
                            case_size_mm = excluded.case_size_mm,
                            movement = excluded.movement,
                            case_material = excluded.case_material,
                            bracelet_strap = excluded.bracelet_strap,
                            dial_color = excluded.dial_color,
                            water_resistance_m = excluded.water_resistance_m,
                            buckle = excluded.buckle,
                            warranty_years = excluded.warranty_years,
                            collection = excluded.collection,
                            movement_caliber = excluded.movement_caliber,
                            case_thickness_mm = excluded.case_thickness_mm,
                            lug_width_mm = excluded.lug_width_mm,
                            remarks = excluded.remarks,
                            updated_at = CURRENT_TIMESTAMP
                    ''', (
                        brand, reference, data['price_jpy'], data['case_size_mm'],
                        data['movement'], data['case_material'], data['bracelet_strap'],
                        data['dial_color'], data['water_resistance_m'], data['buckle'],
                        data['warranty_years'], data['collection'], data['movement_caliber'],
                        data['case_thickness_mm'], data['lug_width_mm'], data['remarks']
                    ))

                    if existing:
                        updated_count += 1
                    else:
                        inserted_count += 1

                except sqlite3.Error as e:
                    error_count += 1
                    error_details.append(f'行{row_num}: データベースエラー - {str(e)}')

            error_details_str = '\n'.join(error_details) if error_details else ''
            sample_diffs_str = json.dumps(sample_diffs, ensure_ascii=False) if sample_diffs else None

            cursor.execute('''
                INSERT INTO master_uploads
                (filename, total_rows, inserted_count, updated_count, error_count, error_details,
                 changed_count, override_conflict_count, sample_diffs)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                file.filename, total_rows, inserted_count, updated_count, error_count, error_details_str,
                changed_count, override_conflict_count, sample_diffs_str
            ))

            conn.commit()

            flash(
                f'インポート完了: 総行数={total_rows}, 新規={inserted_count}, 更新={updated_count}, '
                f'エラー={error_count}, 変更={changed_count}, オーバーライド競合={override_conflict_count}',
                'success'
            )
            if error_details:
                flash(f'エラー詳細: {"; ".join(error_details[:5])}', 'warning')

        except Exception as e:
            flash(f'CSV取込中にエラーが発生しました: {e}', 'error')
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

        return redirect(url_for('admin_upload'))

    conn = get_db_connection()
    latest_upload = conn.execute('''
        SELECT * FROM master_uploads
        ORDER BY uploaded_at DESC LIMIT 1
    ''').fetchone()

    sample_diffs = None
    if latest_upload and latest_upload['sample_diffs']:
        try:
            sample_diffs = json.loads(latest_upload['sample_diffs'])
        except Exception:
            sample_diffs = None

    conn.close()
    return render_template('admin.html', latest_upload=latest_upload, sample_diffs=sample_diffs)


def _build_history_rows(rows):
    out = []
    for r in rows:
        payload = {}
        try:
            payload = json.loads(r['payload_json']) if r['payload_json'] else {}
        except Exception:
            payload = {}

        out.append({
            "id": r["id"],
            "created_at": r["created_at"],
            "intro_text": r["intro_text"] or "",
            "specs_text": r["specs_text"] or "",
            "selected_reference_url": payload.get("selected_reference_url", "") or payload.get("reference_url", "") or "",
            "selected_reference_reason": payload.get("selected_reference_reason", "") or "",
        })
    return out


@app.route('/staff/search', methods=['GET', 'POST'])
def staff_search():
    fields = [
        'price_jpy', 'case_size_mm', 'movement', 'case_material',
        'bracelet_strap', 'dial_color', 'water_resistance_m', 'buckle',
        'warranty_years', 'collection', 'movement_caliber',
        'case_thickness_mm', 'lug_width_mm', 'remarks',
    ]

    # ★テンプレ側で is defined が必ず成立するようにデフォルトを用意
    debug_defaults = {
        "combined_reference_chars": 0,
        "combined_reference_preview": "",
        "reference_urls_debug": [],
    }

    if request.method == 'POST':
        action = request.form.get('action', '').strip()

        if action == 'search':
            brand = request.form.get('brand', '').strip()
            reference = request.form.get('reference', '').strip()
            if not brand or not reference:
                flash('ブランドとリファレンスを入力してください', 'error')
                return render_template('search.html', brands=BRANDS, **debug_defaults)
            return redirect(url_for('staff_search', brand=brand, reference=reference))

        if action == 'save_override':
            brand = request.form.get('brand', '').strip()
            reference = request.form.get('reference', '').strip()
            if not brand or not reference:
                flash('ブランドとリファレンスを入力してください', 'error')
                return render_template('search.html', brands=BRANDS, **debug_defaults)

            data = {'brand': brand, 'reference': reference}
            for f in fields:
                data[f] = request.form.get(f, '').strip()
            data['editor_note'] = request.form.get('editor_note', '').strip()

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO product_overrides
                (brand, reference, price_jpy, case_size_mm, movement, case_material,
                 bracelet_strap, dial_color, water_resistance_m, buckle, warranty_years,
                 collection, movement_caliber, case_thickness_mm, lug_width_mm, remarks, editor_note, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(brand, reference) DO UPDATE SET
                    price_jpy = excluded.price_jpy,
                    case_size_mm = excluded.case_size_mm,
                    movement = excluded.movement,
                    case_material = excluded.case_material,
                    bracelet_strap = excluded.bracelet_strap,
                    dial_color = excluded.dial_color,
                    water_resistance_m = excluded.water_resistance_m,
                    buckle = excluded.buckle,
                    warranty_years = excluded.warranty_years,
                    collection = excluded.collection,
                    movement_caliber = excluded.movement_caliber,
                    case_thickness_mm = excluded.case_thickness_mm,
                    lug_width_mm = excluded.lug_width_mm,
                    remarks = excluded.remarks,
                    editor_note = excluded.editor_note,
                    updated_at = CURRENT_TIMESTAMP
            ''', (
                data['brand'], data['reference'], data['price_jpy'], data['case_size_mm'],
                data['movement'], data['case_material'], data['bracelet_strap'],
                data['dial_color'], data['water_resistance_m'], data['buckle'],
                data['warranty_years'], data['collection'], data['movement_caliber'],
                data['case_thickness_mm'], data['lug_width_mm'], data['remarks'],
                data['editor_note']
            ))
            conn.commit()
            conn.close()

            flash('オーバーライドを保存しました', 'success')
            return redirect(url_for('staff_search', brand=brand, reference=reference))

        if action == 'delete_override':
            brand = request.form.get('brand', '').strip()
            reference = request.form.get('reference', '').strip()
            if not brand or not reference:
                flash('ブランドとリファレンスを入力してください', 'error')
                return redirect(url_for('staff_search'))

            conn = get_db_connection()
            conn.execute('''
                DELETE FROM product_overrides
                WHERE brand = ? AND reference = ?
            ''', (brand, reference))
            conn.commit()
            conn.close()

            flash('オーバーライドを解除しました（マスタに戻しました）', 'success')
            return redirect(url_for('staff_search', brand=brand, reference=reference))

        if action == 'generate_dummy':
            brand = request.form.get('brand', '').strip()
            reference = request.form.get('reference', '').strip()
            if not brand or not reference:
                flash('ブランドとリファレンスを入力してください', 'error')
                return redirect(url_for('staff_search'))

            raw_urls = [
                request.form.get('reference_url_1', '').strip(),
                request.form.get('reference_url_2', '').strip(),
                request.form.get('reference_url_3', '').strip(),
            ]

            reference_urls = []
            for u in raw_urls:
                if not u:
                    continue
                allowed, host, _policy = llmc.get_source_policy(u)
                if not allowed:
                    flash(f'このURLは信頼ソース未登録のため取得しません: {host}', 'warning')
                    continue
                reference_urls.append(u)
            reference_urls = reference_urls[:3]

            conn = get_db_connection()
            master = conn.execute('''
                SELECT * FROM master_products
                WHERE brand = ? AND reference = ?
            ''', (brand, reference)).fetchone()

            override = conn.execute('''
                SELECT * FROM product_overrides
                WHERE brand = ? AND reference = ?
            ''', (brand, reference)).fetchone()

            canonical = {}
            for f in fields:
                ov = override[f] if override and override[f] else ''
                ms = master[f] if master and master[f] else ''
                canonical[f] = ov if ov else ms

            editor_note = (override['editor_note'] if override and 'editor_note' in override.keys() and override['editor_note'] else '')
            conn.close()

            tone_ui = request.form.get('tone', 'practical').strip()
            tone_map = {
                "practical": "practical",
                "luxury": "luxury",
                "magazine": "magazine_story",
                "magazine_story": "magazine_story",
                "casual_friendly": "casual_friendly",
                "ec": "practical",
            }
            tone = tone_map.get(tone_ui, "practical")

            include_brand_profile = request.form.get('include_brand_profile') == 'on'
            include_wearing_scenes = request.form.get('include_wearing_scenes') == 'on'

            payload = {
                'product': {'brand': brand, 'reference': reference},
                'facts': canonical,
                'style': {'tone': tone, 'writing_variant_id': 1},
                'options': {
                    'include_brand_profile': include_brand_profile,
                    'include_wearing_scenes': include_wearing_scenes
                },
                'constraints': {'target_intro_chars': 1500, 'max_specs_chars': 1000},
                'editor_note': editor_note,
                'reference_urls': reference_urls,
                'reference_url': reference_urls[0] if reference_urls else "",
            }

            try:
                intro_text, specs_text, ref_meta = llmc.generate_article(payload)


                payload["selected_reference_url"] = ref_meta.get("selected_reference_url", "")
                payload["selected_reference_reason"] = ref_meta.get("selected_reference_reason", "")
                payload["selected_reference_chars"] = ref_meta.get("selected_reference_chars", 0)

                payload["combined_reference_chars"] = ref_meta.get("combined_reference_chars", 0)
                payload["combined_reference_preview"] = ref_meta.get("combined_reference_preview", "")
                payload["reference_urls_debug"] = ref_meta.get("reference_urls_debug", [])

            except Exception as e:
                flash(f'記事生成中にエラーが発生しました: {e}', 'error')
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            try:
                conn_save = get_db_connection()
                conn_save.execute("""
                    INSERT INTO generated_articles
                    (brand, reference, payload_json, intro_text, specs_text)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    brand,
                    reference,
                    json.dumps(payload, ensure_ascii=False),
                    intro_text,
                    specs_text
                ))
                conn_save.commit()
                conn_save.close()
            except Exception as e:
                flash(f'生成履歴の保存に失敗しました: {e}', 'error')

            conn = get_db_connection()
            master = conn.execute('''
                SELECT * FROM master_products
                WHERE brand = ? AND reference = ?
            ''', (brand, reference)).fetchone()

            override = conn.execute('''
                SELECT * FROM product_overrides
                WHERE brand = ? AND reference = ?
            ''', (brand, reference)).fetchone()

            canonical = {}
            overridden_fields = set()
            for f in fields:
                ov = override[f] if override and override[f] else ''
                ms = master[f] if master and master[f] else ''
                canonical[f] = ov if ov else ms
                if ov:
                    overridden_fields.add(f)

            warnings = []
            override_warning = None
            import_conflict_warning = None

            if not master:
                warnings.append('商品マスタに存在しません。任意入力してください')
            if not canonical.get('price_jpy'):
                warnings.append('price_jpyがマスタとオーバーライドの両方で空です')

            if override:
                override_warning = 'この商品にはオーバーライドが設定されています'

            history_rows = conn.execute("""
                SELECT id, intro_text, specs_text, payload_json, created_at
                FROM generated_articles
                WHERE brand = ? AND reference = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 5
            """, (brand, reference)).fetchall()
            conn.close()
            history = _build_history_rows(history_rows)

            return render_template(
                'search.html',
                brands=BRANDS,
                brand=brand,
                reference=reference,
                master=master,
                override=override,
                canonical=canonical,
                overridden_fields=overridden_fields,
                warnings=warnings,
                override_warning=override_warning,
                import_conflict_warning=import_conflict_warning,
                generated_intro_text=intro_text,
                generated_specs_text=specs_text,
                generation_tone=tone,
                generation_include_brand_profile=include_brand_profile,
                generation_include_wearing_scenes=include_wearing_scenes,
                generation_reference_urls=reference_urls,
                selected_reference_url=payload.get("selected_reference_url", ""),
                selected_reference_reason=payload.get("selected_reference_reason", ""),
                history=history,
                llm_client_file=llmc.__file__,
                llm_client_has_debug_keys=("combined_reference_chars" in (payload or {})),
                raw_urls_debug=raw_urls,
                # ★デバッグ値を必ずテンプレへ渡す
                combined_reference_chars=payload.get("combined_reference_chars", 0),
                combined_reference_preview=payload.get("combined_reference_preview", ""),
                reference_urls_debug=payload.get("reference_urls_debug", []),
            )

        if action == 'regenerate_from_history':
            history_id = request.form.get('history_id')
            brand = request.form.get('brand', '').strip()
            reference = request.form.get('reference', '').strip()

            if not history_id:
                flash('再生成対象の履歴が見つかりません', 'error')
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            conn = get_db_connection()
            history_row = conn.execute(
                "SELECT * FROM generated_articles WHERE id = ?",
                (history_id,)
            ).fetchone()

            if not history_row:
                conn.close()
                flash('指定された生成履歴が存在しません', 'error')
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            payload = {}
            try:
                payload = json.loads(history_row['payload_json'])
            except Exception:
                payload = {}

            try:
                intro_text, specs_text, ref_meta = generate_article(payload)

                payload["selected_reference_url"] = ref_meta.get("selected_reference_url", "")
                payload["selected_reference_reason"] = ref_meta.get("selected_reference_reason", "")
                payload["selected_reference_chars"] = ref_meta.get("selected_reference_chars", 0)

                payload["combined_reference_chars"] = ref_meta.get("combined_reference_chars", 0)
                payload["combined_reference_preview"] = ref_meta.get("combined_reference_preview", "")
                payload["reference_urls_debug"] = ref_meta.get("reference_urls_debug", [])

            except Exception as e:
                conn.close()
                flash(f'再生成中にエラーが発生しました: {e}', 'error')
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            conn.execute(
                """
                INSERT INTO generated_articles
                (brand, reference, payload_json, intro_text, specs_text)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    brand,
                    reference,
                    json.dumps(payload, ensure_ascii=False),
                    intro_text,
                    specs_text
                )
            )
            conn.commit()

            master = conn.execute(
                "SELECT * FROM master_products WHERE brand = ? AND reference = ?",
                (brand, reference)
            ).fetchone()

            override = conn.execute(
                "SELECT * FROM product_overrides WHERE brand = ? AND reference = ?",
                (brand, reference)
            ).fetchone()

            canonical = {}
            overridden_fields = set()
            for f in fields:
                ov = override[f] if override and override[f] else ''
                ms = master[f] if master and master[f] else ''
                canonical[f] = ov if ov else ms
                if ov:
                    overridden_fields.add(f)

            history_rows = conn.execute("""
                SELECT id, intro_text, specs_text, payload_json, created_at
                FROM generated_articles
                WHERE brand = ? AND reference = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 5
            """, (brand, reference)).fetchall()

            conn.close()
            history = _build_history_rows(history_rows)

            return render_template(
                'search.html',
                brands=BRANDS,
                brand=brand,
                reference=reference,
                master=master,
                override=override,
                canonical=canonical,
                overridden_fields=overridden_fields,
                generated_intro_text=intro_text,
                generated_specs_text=specs_text,
                generation_tone=(payload.get('style', {}) or {}).get('tone'),
                generation_include_brand_profile=(payload.get('options', {}) or {}).get('include_brand_profile'),
                generation_include_wearing_scenes=(payload.get('options', {}) or {}).get('include_wearing_scenes'),
                selected_reference_url=payload.get("selected_reference_url", ""),
                selected_reference_reason=payload.get("selected_reference_reason", ""),
                history=history,
                # ★デバッグ値を必ずテンプレへ渡す
                combined_reference_chars=payload.get("combined_reference_chars", 0),
                combined_reference_preview=payload.get("combined_reference_preview", ""),
                reference_urls_debug=payload.get("reference_urls_debug", []),
            )

        flash('不明な操作です', 'error')
        return redirect(url_for('staff_search'))

    # GET
    brand = request.args.get('brand', '').strip()
    reference = request.args.get('reference', '').strip()

    master = None
    override = None
    canonical = {}
    overridden_fields = set()
    warnings = []
    override_warning = None
    import_conflict_warning = None
    history = []

    if brand and reference:
        conn = get_db_connection()

        master = conn.execute('''
            SELECT * FROM master_products
            WHERE brand = ? AND reference = ?
        ''', (brand, reference)).fetchone()

        override = conn.execute('''
            SELECT * FROM product_overrides
            WHERE brand = ? AND reference = ?
        ''', (brand, reference)).fetchone()

        for f in fields:
            ov = override[f] if override and override[f] else ''
            ms = master[f] if master and master[f] else ''
            canonical[f] = ov if ov else ms
            if ov:
                overridden_fields.add(f)

        if not master:
            warnings.append('商品マスタに存在しません。任意入力してください')
        if not canonical.get('price_jpy'):
            warnings.append('price_jpyがマスタとオーバーライドの両方で空です')

        if override:
            override_warning = 'この商品にはオーバーライドが設定されています'

        history_rows = conn.execute("""
            SELECT id, intro_text, specs_text, payload_json, created_at
            FROM generated_articles
            WHERE brand = ? AND reference = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 5
        """, (brand, reference)).fetchall()

        conn.close()
        history = _build_history_rows(history_rows)

    return render_template(
        'search.html',
        brands=BRANDS,
        brand=brand,
        reference=reference,
        master=master,
        override=override,
        canonical=canonical,
        overridden_fields=overridden_fields,
        warnings=warnings,
        override_warning=override_warning,
        import_conflict_warning=import_conflict_warning,
        history=history,
        # ★GETでも定義しておく（テンプレ側が安定する）
        **debug_defaults
    )


if __name__ == "__main__":
    app.run(debug=False, use_reloader=False, port=5000)
