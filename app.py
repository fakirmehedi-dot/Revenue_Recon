"""
Revenue Reconciliation Portal  –  Phase 1 + Phase 2
Run: streamlit run app.py
"""
import io, zipfile, datetime, traceback
import pandas as pd
import streamlit as st

from engine.loader  import load_file, concat_files, normalize, find_col, to_numeric_col
from engine.phase1  import reconcile_all
from engine.phase2  import reconcile_phase2
from engine.writer  import write_outputs

st.set_page_config(page_title="Revenue Reconciliation Portal", page_icon="💰",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
.rc-title{font-size:26px;font-weight:700;color:#1a1a18;margin-bottom:2px}
.rc-sub{font-size:13px;color:#73726c;margin-bottom:20px}
.rc-section{font-size:14px;font-weight:600;color:#1a1a18;margin:18px 0 8px;
            padding-bottom:6px;border-bottom:1.5px solid #d3d1c7}
.metric-box{background:#f8f8f6;border:1px solid #d3d1c7;border-radius:8px;
            padding:12px 14px;text-align:center}
.metric-val{font-size:26px;font-weight:700;color:#1a4fd6}
.metric-lbl{font-size:11px;color:#73726c;margin-top:2px}
.phase-badge{display:inline-block;font-size:11px;font-weight:600;padding:2px 8px;
             border-radius:20px;margin-left:6px}
</style>
""", unsafe_allow_html=True)

# ── Session state init ────────────────────────────────────────────────────────
if "results"    not in st.session_state: st.session_state.results    = None
if "out_files"  not in st.session_state: st.session_state.out_files  = None
if "run_done"   not in st.session_state: st.session_state.run_done   = False

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Settings")
    cs, ce = st.columns(2)
    with cs:
        start_date = st.date_input("From", value=datetime.date(2026, 3, 1), label_visibility="collapsed")
    with ce:
        end_date = st.date_input("To", value=datetime.date(2026, 4, 21), label_visibility="collapsed")
    st.caption(f"📅 {start_date} → {end_date}")

    out_fmt = st.radio("Output format", ["XLSX", "CSV", "Both"], index=0, horizontal=True)
    st.markdown("**Tolerances**")
    tol_usd  = st.number_input("USD ($)",           value=0.01, step=0.01, format="%.2f")
    tol_usdt = st.number_input("USDT / crypto ($)", value=0.10, step=0.01, format="%.2f")
    st.markdown("---")
    st.markdown("""
**Required API columns**  
`Transaction ID` · `Tracking ID`  
`Grand Total` · `Status` · `Created At`
    """)

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown('<div class="rc-title">💰 Revenue Reconciliation Portal</div>', unsafe_allow_html=True)
st.markdown('<div class="rc-sub">Upload → Run → Download  ·  Phase 1 (API vs Banks) + Phase 2 (Orchestrators vs PSPs)</div>', unsafe_allow_html=True)

tab_upload, tab_run = st.tabs(["📁  Upload files", "🚀  Run & Download"])

# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — UPLOAD
# ════════════════════════════════════════════════════════════════════════════
with tab_upload:

    st.markdown('<div class="rc-section">API Data — Source of Truth</div>', unsafe_allow_html=True)
    api_files = st.file_uploader("API order files (1–3 CSV/XLSX)", accept_multiple_files=True,
                                 type=["csv","xlsx","xls"], key="api")
    if api_files:
        try:
            prev = normalize(concat_files(api_files))
            st.success(f"✅ {len(prev):,} rows · {len(prev.columns)} columns")
            with st.expander("Columns detected"):
                st.write(list(prev.columns))
        except Exception as e:
            st.error(f"Load error: {e}")

    # ── Phase 1 ──────────────────────────────────────────────────────────────
    st.markdown('<div class="rc-section">Phase 1 — Bank Statements <span class="phase-badge" style="background:#dbeafe;color:#1e40af">Required for Phase 1</span></div>', unsafe_allow_html=True)

    cL, cR = st.columns(2)
    with cL:
        st.markdown("**🔷 Bridgerpay** — Orchestrator")
        st.caption("`Transaction ID (BP_*)` = `merchantOrderId` | `status=approved`")
        bp_files = st.file_uploader("", accept_multiple_files=True, type=["csv","xlsx","xls"], key="bp", label_visibility="collapsed")

        st.markdown("**🔷 Payprocc** — Orchestrator")
        st.caption("`Transaction ID (PP_*)` = `Merchant Order ID` | `type=sale & status=success`")
        pp_files = st.file_uploader("", accept_multiple_files=True, type=["csv","xlsx","xls"], key="pp", label_visibility="collapsed")

        st.markdown("**🟢 Coinsbuy** — Independent")
        st.caption("`Tracking ID (B2B_*)` = `Tracking ID` | SUM duplicates | ±$0.10")
        cb_files = st.file_uploader("", accept_multiple_files=True, type=["csv","xlsx","xls"], key="cb", label_visibility="collapsed")

    with cR:
        st.markdown("**🟢 ZEN** — Independent")
        st.caption("`Transaction ID (ZP_*)` = `merchant_transaction_id` | `ACCEPTED`")
        zen_files = st.file_uploader("", accept_multiple_files=True, type=["csv","xlsx","xls"], key="zen", label_visibility="collapsed")

        st.markdown("**🟢 Confirmo** — Independent (April direct)")
        st.caption("`Tracking ID (CFM_*)` = `Reference` | `ReferenceValueWithoutFee`")
        cfm_files = st.file_uploader("", accept_multiple_files=True, type=["csv","xlsx","xls"], key="cfm", label_visibility="collapsed")

        st.markdown("**🟢 TC Pay** — Independent")
        st.caption("TC `Tracking Number` ⊆ API `Transaction ID (OP-...)` | `Increase`")
        tcp_files = st.file_uploader("", accept_multiple_files=True, type=["csv","xlsx","xls"], key="tcp", label_visibility="collapsed")

    # ── Phase 2 ──────────────────────────────────────────────────────────────
    st.markdown('<div class="rc-section">Phase 2 — PSP Statements <span class="phase-badge" style="background:#fef3c7;color:#92400e">Optional — deeper verification</span></div>', unsafe_allow_html=True)

    with st.expander("📂 PSPs under Bridgerpay"):
        b2a, b2b, b2c = st.columns(3)
        with b2a:
            paypal_f   = st.file_uploader("PayPal — `transactionId`=`Transaction ID` | Gross",        type=["csv","xlsx","xls"], key="p2_paypal")
            unlimit_f  = st.file_uploader("Unlimit ×3 — `pspOrderId`=`Payment ID`",                   type=["csv","xlsx","xls"], key="p2_unlimit")
            nuvei_ni_f = st.file_uploader("Nuvei NI — `merchantOrderId`=`Custom Data` | Sale",        type=["csv","xlsx","xls"], key="p2_nuvei_ni")
            nuvei_aq_f = st.file_uploader("Nuvei AQ — `merchantOrderId`=`Custom Data` | Sale",        type=["csv","xlsx","xls"], key="p2_nuvei_aq")
        with b2b:
            axcess_f   = st.file_uploader("Axcess/Truevo ×3 — `merchantOrderId`=`InvoiceId`",         type=["csv","xlsx","xls"], key="p2_axcess")
            cfm_p2_f   = st.file_uploader("Confirmo (Mar via BP) — `pspOrderId`=`ID`",                type=["csv","xlsx","xls"], key="p2_cfm")
            trustpay_f = st.file_uploader("Trust Payment — `transactionId`=`Reference`",              type=["csv","xlsx","xls"], key="p2_trust")
        with b2c:
            payabl_f   = st.file_uploader("Payabl ×3 — `merchantOrderId`=`Custom 3`",                 type=["csv","xlsx","xls"], key="p2_payabl")
            paysafe_f  = st.file_uploader("Paysafe (BP) — `transactionId`=`Transaction ID`",          type=["csv","xlsx","xls"], key="p2_paysafe_bp")

    with st.expander("📂 PSPs under Payprocc"):
        p2a, p2b, p2c = st.columns(3)
        with p2a:
            dlocal_f     = st.file_uploader("DLocal — `Payment Public ID`=`Invoice`",                 type=["csv","xlsx","xls"], key="p2_dlocal")
        with p2b:
            skrill_f     = st.file_uploader("Skrill EEA+ROW — `Payment Public ID`=`Reference`",       type=["csv","xlsx","xls"], key="p2_skrill")
        with p2c:
            paysafe_pp_f = st.file_uploader("Paysafe (PP) — `Payment Public ID`=`Merchant TxID`",    type=["csv","xlsx","xls"], key="p2_paysafe_pp")

# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — RUN & DOWNLOAD
# ════════════════════════════════════════════════════════════════════════════
with tab_run:

    bank_map = {
        "bridgerpay": bp_files  or [],
        "payprocc":   pp_files  or [],
        "coinsbuy":   cb_files  or [],
        "zen":        zen_files or [],
        "confirmo":   cfm_files or [],
        "tcpay":      tcp_files or [],
    }
    uploaded_banks = [k for k, v in bank_map.items() if v]

    psp_map = {
        "paypal":     [paypal_f]   if paypal_f   else [],
        "unlimit":    [unlimit_f]  if unlimit_f  else [],
        "nuvei_ni":   [nuvei_ni_f] if nuvei_ni_f else [],
        "nuvei_aq":   [nuvei_aq_f] if nuvei_aq_f else [],
        "axcess":     [axcess_f]   if axcess_f   else [],
        "confirmo_bp":[cfm_p2_f]  if cfm_p2_f  else [],
        "trustpay":   [trustpay_f] if trustpay_f else [],
        "payabl":     [payabl_f]   if payabl_f   else [],
        "paysafe_bp": [paysafe_f]  if paysafe_f  else [],
        "dlocal":     [dlocal_f]   if dlocal_f   else [],
        "skrill":     [skrill_f]   if skrill_f   else [],
        "paysafe_pp": [paysafe_pp_f] if paysafe_pp_f else [],
    }
    uploaded_psps = [k for k, v in psp_map.items() if v]

    if not api_files:
        st.info("👆 Go to Upload files and add the API file to get started.")
    else:
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            st.success(f"✅ API: {len(api_files)} file(s)")
        with sc2:
            if uploaded_banks:
                st.success(f"✅ Phase 1 banks: {len(uploaded_banks)}")
            else:
                st.warning("⚠️ No bank files")
        with sc3:
            if uploaded_psps:
                st.info(f"📂 Phase 2 PSPs: {len(uploaded_psps)}")
            else:
                st.caption("No Phase 2 PSPs (optional)")

        st.markdown("---")
        run_btn = st.button("🚀  Run Reconciliation", type="primary",
                            use_container_width=True, disabled=not bool(uploaded_banks))
        if not uploaded_banks:
            st.caption("Upload at least one Phase 1 bank statement to enable this button.")

        # ── Run ──────────────────────────────────────────────────────────────
        if run_btn:
            st.session_state.run_done  = False
            st.session_state.results   = None
            st.session_state.out_files = None

            pb  = st.progress(0, text="Starting…")
            stx = st.empty()

            def upd(pct, msg):
                pb.progress(pct, text=msg)
                stx.caption(msg)

            try:
                upd(5, "Loading API data…")
                api_raw = concat_files(api_files)
                api_df  = normalize(api_raw)

                status_col = find_col(api_df, ["Status","status"])
                date_col   = find_col(api_df, ["Created At","CreatedAt","created_at"])

                if status_col:
                    api_en = api_df[api_df[status_col].astype(str).str.lower() == "enabled"].copy()
                else:
                    api_en = api_df.copy()
                    st.warning("No 'Status' column — using all rows.")

                if date_col:
                    api_en[date_col] = pd.to_datetime(api_en[date_col], errors="coerce")
                    api_en = api_en[
                        (api_en[date_col] >= pd.Timestamp(start_date)) &
                        (api_en[date_col] <= pd.Timestamp(end_date) + pd.Timedelta(days=1))
                    ]

                upd(20, f"API: {len(api_en):,} enabled orders in period")

                # Phase 1
                results, errors = reconcile_all(api_en, bank_map,
                                                tol_usd=tol_usd, tol_usdt=tol_usdt,
                                                progress_cb=upd)
                for bk, err in errors.items():
                    st.warning(f"⚠️ Phase 1 — {bk}: {err}")

                # Phase 2
                if uploaded_psps:
                    upd(80, "Running Phase 2 — PSP reconciliation…")
                    p2_results, p2_errors = reconcile_phase2(results, psp_map, tol_usd=tol_usd)
                    for bk, err in p2_errors.items():
                        st.warning(f"⚠️ Phase 2 — {bk}: {err}")
                    results["phase2"] = p2_results

                upd(88, "Generating output files…")
                out_files = write_outputs(results, api_df, start_date, end_date, out_fmt)

                # ── Store in session state so downloads survive reruns ─────
                st.session_state.results   = results
                st.session_state.out_files = out_files
                st.session_state.run_done  = True
                st.session_state.api_df    = api_en

                pb.progress(100, text="✅ Complete!")
                stx.empty()

            except Exception as exc:
                pb.progress(0, text="Error")
                st.error(f"❌ Failed: {exc}")
                with st.expander("Full traceback"):
                    st.code(traceback.format_exc())

        # ── Results (shown from session_state — survives download clicks) ───
        if st.session_state.run_done and st.session_state.results:
            results   = st.session_state.results
            out_files = st.session_state.out_files

            st.success("🎉 Reconciliation complete!")

            # ── Main summary table ──────────────────────────────────────────────
            try:
                from engine.report_summary import compute_summary_stats
                _api_df = st.session_state.get("api_df", pd.DataFrame())
                stats = compute_summary_stats(_api_df, results)
                if stats:
                    def _fmt(v, is_rev=False):
                        return f"${v:,.2f}" if is_rev else f"{int(v):,}"
                    s = stats
                    st.markdown("#### Reconciliation Summary")
                    st.markdown("""<style>
.rtbl{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:10px}
.rtbl th{background:#1e3a5f;color:#fff;padding:6px 10px;text-align:center;border:1px solid #aaa}
.rtbl td{padding:6px 10px;text-align:right;border:1px solid #e0e0e0}
.rtbl td.lbl{text-align:left;font-weight:600;background:#f0f4ff}
.dr{color:#c00000;font-weight:600}
</style>""", unsafe_allow_html=True)
                    st.markdown(f"""<table class='rtbl'>
<tr><th rowspan='2'>Metric</th>
<th colspan='5' style='background:#1e4fd6'>Orders</th>
<th colspan='5' style='background:#065f46'>Revenue (USD)</th></tr>
<tr><th>API</th><th>Orchestrator</th><th>Diff (API-Orch)</th><th>PSP Reconciled</th><th>Diff (API-PSP)</th>
<th>API</th><th>Orchestrator</th><th>Diff (API-Orch)</th><th>PSP Reconciled</th><th>Diff (API-PSP)</th></tr>
<tr><td class='lbl'>Full Period</td>
<td>{_fmt(s['api_orders'])}</td><td>{_fmt(s['orch_orders'])}</td>
<td class='dr'>{_fmt(s['diff_orch'])}</td>
<td>{_fmt(s['psp_orders'])}</td><td class='dr'>{_fmt(s['diff_psp'])}</td>
<td>{_fmt(s['api_rev'],True)}</td><td>{_fmt(s['orch_rev'],True)}</td>
<td class='dr'>{_fmt(s['diff_orch_rev'],True)}</td>
<td>{_fmt(s['psp_rev'],True)}</td><td class='dr'>{_fmt(s['diff_psp_rev'],True)}</td>
</tr></table>""", unsafe_allow_html=True)
            except Exception as _se:
                st.warning(f"Summary table: {_se}")

            # ── Phase 1 by bank ─────────────────────────────────────────────────
            if "combined" in results:
                st.markdown("**Phase 1 — Results by bank**")
                comb = results["combined"]
                rows = []
                for bank in comb["Bank"].dropna().unique():
                    sub = comb[comb["Bank"] == bank]
                    rec = (sub["Verdict"] == "RECONCILED").sum()
                    mis = (sub["Verdict"] == "AMOUNT MISMATCH").sum()
                    nib = (sub["Verdict"] == "NOT IN BANK").sum()
                    pct = rec / len(sub) * 100 if len(sub) else 0
                    rows.append({"Bank": bank, "Total": len(sub), "Reconciled": int(rec),
                                 "Match %": f"{pct:.1f}%", "Mismatch": int(mis), "Not In Bank": int(nib)})
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            # ── Phase 2 by PSP ──────────────────────────────────────────────────
            if "phase2" in results:
                p2 = results["phase2"]
                if p2:
                    st.markdown("**Phase 2 — Results by PSP**")
                    rows2 = []
                    for psp_key, df2 in p2.items():
                        if isinstance(df2, pd.DataFrame) and not df2.empty and "Verdict" in df2.columns:
                            rec = (df2["Verdict"] == "RECONCILED").sum()
                            mis = (df2["Verdict"] == "AMOUNT MISMATCH").sum()
                            nio = (df2["Verdict"] == "NOT IN ORCH").sum()
                            pct = rec / len(df2) * 100 if len(df2) else 0
                            rows2.append({"PSP": psp_key.replace("_"," ").title(),
                                          "PSP Rows": len(df2), "Reconciled": int(rec),
                                          "Match %": f"{pct:.1f}%", "Mismatch": int(mis),
                                          "Not In Orch": int(nio)})
                    if rows2:
                        st.dataframe(pd.DataFrame(rows2), use_container_width=True, hide_index=True)
                else:
                    st.info("No Phase 2 PSP files were uploaded.")

            st.markdown("---")
            st.markdown("### 📥 Download results")
            st.caption("Files stay available — clicking download will not reset the results.")

            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for fn, fb in out_files.items():
                    fb.seek(0)
                    zf.writestr(fn, fb.read())

            d1, d2 = st.columns(2)
            with d1:
                zip_buf.seek(0)
                st.download_button("⬇️  Download all (ZIP)", data=zip_buf.getvalue(),
                                   file_name=f"Reconciliation_{start_date}_{end_date}.zip",
                                   mime="application/zip", use_container_width=True)
            with d2:
                sk = f"Summary_{start_date}_{end_date}.xlsx"
                if sk in out_files:
                    out_files[sk].seek(0)
                    st.download_button("⬇️  Summary only (XLSX)", data=out_files[sk].getvalue(),
                                       file_name=sk,
                                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                       use_container_width=True)

            with st.expander("Individual file downloads"):
                for fn, fb in out_files.items():
                    fb.seek(0)
                    ext  = fn.rsplit(".", 1)[-1]
                    mime = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                            if ext == "xlsx" else "text/csv")
                    st.download_button(f"⬇️  {fn}", data=fb.getvalue(),
                                       file_name=fn, mime=mime, key=f"dl_{fn}")
