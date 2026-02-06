from flask import Flask, render_template, request, redirect, url_for, flash
import json
import csv
import io
import os
import sqlite3
from datetime import datetime, timedelta

from models import init_db, get_db_connection, REQUIRED_CSV_COLUMNS
import llm_client as llmc
from url_discovery import discover_reference_urls

# ----------------------------
# Plan / quota settings
# ----------------------------
PLAN_MODE = os.getenv("HOROLOGEN_PLAN", "limited").strip().lower()  # "limited" / "unlimited"
MONTHLY_LIMIT = int(os.getenv("HOROLOGEN_MONTHLY_LIMIT", "30"))

# ----------------------------
# Flask
# ----------------------------
app = Flask(__name__)
init_db()
app.secret_key = 'horologen-secret-key-change-in-production'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

BRANDS = ['cartier', 'omega', 'grand_seiko', 'iwc', 'panerai']


# ----------------------------
# Error humanizer (public message) + log detail
# ----------------------------
def humanize_llm_error(e: Exception) -> str:
    msg = str(e) or ""
    m = msg.lower()

    if "credit balance is too low" in m or "plans & billing" in m:
        return "使用上限に達しました。管理者にお問い合わせください。"
    if "rate limit" in m or "too many requests" in m:
        return "アクセスが集中しています。少し時間を置いてから再度お試しください。"
    if "api key" in m or "authentication" in m or "unauthorized" in m:
        return "認証エラーが発生しました。管理者にお問い合わせください。"
    if "timeout" in m or "timed out" in m or "connection" in m:
        return "通信が不安定です。時間を置いてから再度お試しください。"

    return "エラーが発生しました。管理者にお問い合わせください。"


# ----------------------------
# Quota helpers (service-wide monthly limit)
# ----------------------------
def _month_key_jst() -> str:
    dt = datetime.utcnow() + timedelta(hours=9)
    return dt.strftime("%Y-%m")

def get_monthly_usage(conn) -> int:
    mk = _month_key_jst()
    row = conn.execute(
        "SELECT used_count FROM monthly_generation_usage WHERE month_key = ?",
        (mk,)
    ).fetchone()
    return int(row["used_count"]) if row else 0

def remaining_quota(conn) -> int:
    if PLAN_MODE == "unlimited":
        return 10**9  # display only
    used = get_monthly_usage(conn)
    return max(0, MONTHLY_LIMIT - used)

def consume_quota_or_block(n: int = 1) -> tuple[bool, str]:
    """
    called right before LLM call.
    limited: if exceeded => block. if OK => increment used_count (+n)
    unlimited: always OK
    """
    if PLAN_MODE == "unlimited":
        return True, ""

    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        mk = _month_key_jst()

        row = conn.execute(
            "SELECT used_count FROM monthly_generation_usage WHERE month_key = ?",
            (mk,)
        ).fetchone()
        used = int(row["used_count"]) if row else 0

        if used + n > MONTHLY_LIMIT:
            conn.rollback()
            return False, "今月の生成回数の上限に達しました。管理者にお問い合わせください。"

        if row:
            conn.execute(
                "UPDATE monthly_generation_usage "
                "SET used_count = used_count + ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE month_key = ?",
                (n, mk)
            )
        else:
            conn.execute(
                "INSERT INTO monthly_generation_usage (month_key, used_count) VALUES (?, ?)",
                (mk, n)
            )

        conn.commit()
        return True, ""
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        app.logger.exception("quota check/update failed: %s", e)
        return False, "システム側でエラーが発生しました。管理者にお問い合わせください。"
    finally:
        try:
            conn.close()
        except Exception:
            pass

def get_quota_view() -> tuple[str, int, int]:
    conn = get_db_connection()
    try:
        mk = _month_key_jst()
        used = get_monthly_usage(conn)
        rem = remaining_quota(conn)
        return mk, used, rem
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ----------------------------
# History view helper
# ----------------------------
def _build_history_rows(rows):
    out = []
    for r in rows:
        payload = {}
        try:
            payload = json.loads(r['payload_json']) if r['payload_json'] else {}
        except Exception:
            payload = {}

        created_raw = r["created_at"]  # SQLite UTC
        created_jst = created_raw
        try:
            dt = datetime.strptime(created_raw, "%Y-%m-%d %H:%M:%S")
            created_jst = (dt + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

        # Prefer DB columns if present, fallback to payload (for old records)
        db_depth = None
        db_parent = None
        try:
            db_depth = r["rewrite_depth"]
            db_parent = r["rewrite_parent_id"]
        except Exception:
            pass

        depth = int(db_depth) if db_depth is not None else int(payload.get("rewrite_depth", 0) or 0)
        parent_id = db_parent if db_parent is not None else payload.get("rewrite_parent_id", None)

        out.append({
            "id": r["id"],
            "created_at": created_jst,
            "intro_text": r["intro_text"] or "",
            "specs_text": r["specs_text"] or "",
            "selected_reference_url": payload.get("selected_reference_url", "") or payload.get("reference_url", "") or "",
            "selected_reference_reason": payload.get("selected_reference_reason", "") or "",
            "similarity_percent": payload.get("similarity_percent", 0) or 0,
            "similarity_level": payload.get("similarity_level", "blue") or "blue",
            "rewrite_applied": bool(payload.get("rewrite_applied", False)),

            "rewrite_depth": depth,
            "rewrite_parent_id": parent_id,
        })
    return out


# ----------------------------
# Routes
# ----------------------------
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


@app.route('/staff/search', methods=['GET', 'POST'])
def staff_search():
    fields = [
        'price_jpy', 'case_size_mm', 'movement', 'case_material',
        'bracelet_strap', 'dial_color', 'water_resistance_m', 'buckle',
        'warranty_years', 'collection', 'movement_caliber',
        'case_thickness_mm', 'lug_width_mm', 'remarks',
    ]

    # NOTE: do NOT put plan_mode/monthly_* here (avoid duplicate keyword bugs)
    debug_defaults = {
        "combined_reference_chars": 0,
        "combined_reference_preview": "",
        "reference_urls_debug": [],
        "llm_client_file": llmc.__file__,
        "raw_urls_debug": [],
        "similarity_percent": 0,
        "similarity_level": "blue",
        "saved_article_id": None,
    }

    if request.method == 'POST':
        action = request.form.get('action', '').strip()

        if action == 'search':
            brand = request.form.get('brand', '').strip()
            reference = request.form.get('reference', '').strip()
            if not brand or not reference:
                mk, used, rem = get_quota_view()
                return render_template(
                    'search.html',
                    brands=BRANDS,
                    plan_mode=PLAN_MODE, monthly_limit=MONTHLY_LIMIT, monthly_used=used, monthly_remaining=rem, month_key=mk,
                    **debug_defaults
                )
            return redirect(url_for('staff_search', brand=brand, reference=reference))

        if action == 'save_override':
            brand = request.form.get('brand', '').strip()
            reference = request.form.get('reference', '').strip()
            if not brand or not reference:
                mk, used, rem = get_quota_view()
                return render_template(
                    'search.html',
                    brands=BRANDS,
                    plan_mode=PLAN_MODE, monthly_limit=MONTHLY_LIMIT, monthly_used=used, monthly_remaining=rem, month_key=mk,
                    **debug_defaults
                )

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

        # ----------------------------
        # Generate
        # ----------------------------
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
            raw_urls = [u for u in raw_urls if u]

            if not raw_urls:
                auto_urls, _auto_debug = discover_reference_urls(brand, reference, max_urls=3)
                reference_urls = auto_urls[:3]
            else:
                reference_urls = raw_urls[:3]

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
                "magazine_story": "magazine_story",
                "casual_friendly": "casual_friendly",
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

            ok, msg = consume_quota_or_block(n=1)
            if not ok:
                flash(msg, 'error')
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            try:
                intro_text, specs_text, ref_meta = llmc.generate_article(payload, rewrite_mode="none")
            except Exception as e:
                app.logger.exception("LLM generate_dummy failed: %s", e)
                flash(humanize_llm_error(e), 'error')
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            combined_reference_chars = int(ref_meta.get("combined_reference_chars", 0) or 0)
            combined_reference_preview = ref_meta.get("combined_reference_preview", "") or ""
            reference_urls_debug = ref_meta.get("reference_urls_debug", []) or []
            selected_reference_url = ref_meta.get("selected_reference_url", "") or ""
            selected_reference_reason = ref_meta.get("selected_reference_reason", "") or ""

            similarity_percent = int(ref_meta.get("similarity_percent", 0) or 0)
            similarity_level = (ref_meta.get("similarity_level") or "blue").strip() or "blue"
            rewrite_applied = bool(ref_meta.get("rewrite_applied", False))

            payload["selected_reference_url"] = selected_reference_url
            payload["selected_reference_reason"] = selected_reference_reason
            payload["combined_reference_chars"] = combined_reference_chars
            payload["combined_reference_preview"] = combined_reference_preview
            payload["reference_urls_debug"] = reference_urls_debug
            payload["similarity_percent"] = similarity_percent
            payload["similarity_level"] = similarity_level
            payload["rewrite_applied"] = rewrite_applied

            saved_article_id = None
            try:
                conn_save = get_db_connection()

                payload["rewrite_depth"] = 0
                payload["rewrite_parent_id"] = None
                payload["rewrite_applied"] = False

                cur = conn_save.execute("""
                    INSERT INTO generated_articles
                    (brand, reference, payload_json, intro_text, specs_text, rewrite_depth, rewrite_parent_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    brand,
                    reference,
                    json.dumps(payload, ensure_ascii=False),
                    intro_text,
                    specs_text,
                    0,
                    None
                ))
                conn_save.commit()
                saved_article_id = cur.lastrowid
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

            history_rows = conn.execute("""
                SELECT id, intro_text, specs_text, payload_json, created_at, rewrite_depth, rewrite_parent_id
                FROM generated_articles
                WHERE brand = ? AND reference = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 5
            """, (brand, reference)).fetchall()
            conn.close()
            history = _build_history_rows(history_rows)

            mk, used, rem = get_quota_view()

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
                generation_tone=tone,
                generation_include_brand_profile=include_brand_profile,
                generation_include_wearing_scenes=include_wearing_scenes,
                generation_reference_urls=reference_urls,

                selected_reference_url=selected_reference_url,
                selected_reference_reason=selected_reference_reason,

                history=history,
                combined_reference_chars=combined_reference_chars,
                combined_reference_preview=combined_reference_preview,
                reference_urls_debug=reference_urls_debug,
                llm_client_file=llmc.__file__,
                raw_urls_debug=(raw_urls if raw_urls else reference_urls),

                similarity_percent=similarity_percent,
                similarity_level=similarity_level,

                saved_article_id=saved_article_id,
                rewrite_depth=0,

                plan_mode=PLAN_MODE,
                monthly_limit=MONTHLY_LIMIT,
                monthly_used=used,
                monthly_remaining=rem,
                month_key=mk,
            )

        # ----------------------------
        # Rewrite once (max 1 per source id)
        # ----------------------------
        if action == 'rewrite_once':
            brand = request.form.get('brand', '').strip()
            reference = request.form.get('reference', '').strip()
            source_article_id = request.form.get('source_article_id', '').strip()

            if not (brand and reference and source_article_id.isdigit()):
                flash('言い換え対象が不正です', 'error')
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            conn = get_db_connection()
            row = conn.execute(
                "SELECT * FROM generated_articles WHERE id = ?",
                (int(source_article_id),)
            ).fetchone()

            if not row:
                conn.close()
                flash('言い換え対象の履歴が見つかりません', 'error')
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            payload = {}
            try:
                payload = json.loads(row['payload_json']) if row['payload_json'] else {}
            except Exception:
                payload = {}

            # Server-side guard: same source id can be rewritten only once
            already = conn.execute(
                "SELECT 1 FROM generated_articles WHERE rewrite_parent_id = ? LIMIT 1",
                (int(source_article_id),)
            ).fetchone()
            if already:
                conn.close()
                flash('この履歴は既に言い換え済みのため、再度の言い換えはできません（最大1回）', 'warning')
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            # Prevent rewriting a rewritten record
            src_depth = int(payload.get("rewrite_depth", 0) or 0)
            if src_depth >= 1:
                conn.close()
                flash('この履歴は既に言い換え済みのため、再度の言い換えはできません（最大1回）', 'warning')
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            ok, msg = consume_quota_or_block(n=1)
            if not ok:
                conn.close()
                flash(msg, 'error')
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            try:
                intro_text, specs_text, ref_meta = llmc.generate_article(payload, rewrite_mode="force")
            except Exception as e:
                conn.close()
                app.logger.exception("LLM rewrite_once failed: %s", e)
                flash(humanize_llm_error(e), 'error')
                return redirect(url_for('staff_search', brand=brand, reference=reference))

            payload["selected_reference_url"] = ref_meta.get("selected_reference_url", "")
            payload["selected_reference_reason"] = ref_meta.get("selected_reference_reason", "")
            payload["combined_reference_chars"] = ref_meta.get("combined_reference_chars", 0)
            payload["combined_reference_preview"] = ref_meta.get("combined_reference_preview", "")
            payload["reference_urls_debug"] = ref_meta.get("reference_urls_debug", [])

            similarity_percent = i