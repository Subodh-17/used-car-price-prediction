"""Complete Playwright end-to-end browser audit against the running Uvicorn server."""
import json
import sys
import urllib.error
import urllib.request

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from playwright.sync_api import sync_playwright


def run_browser_audit():
    console_errors = []
    failed_requests = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda err: console_errors.append(str(err)))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}: {req.failure}"))

        print("=== 1. HOMEPAGE TEST ===")
        page.goto("http://127.0.0.1:8000")
        page.wait_for_selector(".bento")
        print("Homepage Title:", page.title())
        overview_text = page.inner_text("body")
        assert "VALUATION" in overview_text or "CarValue" in overview_text
        print("PASS: Homepage loaded with Bento grid.")

        print("\n=== 2. ESTIMATOR PAGE TEST ===")
        page.click('a[href="#/estimate"]')
        page.wait_for_selector("form#f")
        page.wait_for_selector('#make option[value="Maruti Suzuki"]', state="attached")
        print("PASS: Estimator form loaded.")

        # Select Manufacturer
        page.select_option("#make", "Maruti Suzuki")
        page.wait_for_selector('#model option[value="Swift"]', state="attached")
        print("PASS: Cascading models loaded for Maruti Suzuki.")

        # Select Model
        page.select_option("#model", "Swift")
        page.wait_for_selector("#variant option", state="attached")
        print("PASS: Variants and model details loaded for Swift.")

        # Fill form
        page.fill("#year", "2016")
        page.fill("#km_driven", "45000")
        page.select_option("#fuel", "Petrol")
        page.select_option("#transmission", "Manual")

        # Capture predict network request
        with page.expect_response(lambda r: "/api/predict" in r.url and r.status == 200) as response_info:
            page.click("button#go")

        api_resp = response_info.value.json()
        api_price = api_resp["estimated_price_inr"]
        api_interval = api_resp["interval"]
        print(f"API Response: estimated_price_inr = ₹{api_price:,}")
        print(f"API Interval: {api_interval['low_inr']} - {api_interval['high_inr']}")

        page.wait_for_selector("#price")
        displayed_price = page.inner_text("#price")
        print("Displayed Price in UI:", displayed_price)
        clean_disp = displayed_price.replace(",", "").replace("₹", "").strip()
        assert str(api_price) in clean_disp, f"Expected {api_price} in {clean_disp}"
        print("PASS: Displayed price exactly matches API response!")

        range_text = page.inner_text(".range")
        print("Displayed Range in UI:", range_text.splitlines()[0])
        clean_range = range_text.replace(",", "").replace("₹", "")
        assert str(api_interval["low_inr"]) in clean_range
        assert str(api_interval["high_inr"]) in clean_range
        print("PASS: Displayed interval exactly matches API response!")

        print("\n=== 3. CLIENT-SIDE VALIDATION & ERROR HANDLING ===")
        page.reload()
        page.wait_for_selector("form#f")
        page.click("button#go")
        page.wait_for_selector("#summary", state="visible")
        summary_text = page.inner_text("#summary")
        assert "Please fix" in summary_text
        print("PASS: Empty form shows validation summary:", summary_text.splitlines()[0])

        # Test year beyond 2022 rejection in UI
        page.select_option("#make", "Maruti Suzuki")
        page.wait_for_selector('#model option[value="Swift"]', state="attached")
        page.select_option("#model", "Swift")
        page.fill("#year", "2025")
        page.fill("#km_driven", "45000")
        page.click("button#go")
        page.wait_for_selector("#e-year:not(:empty)")
        year_err = page.inner_text("#e-year")
        print("Year 2025 validation error:", year_err)
        assert "2022" in year_err
        print("PASS: Year 2025 rejected by UI validation against valuation_year!")

        print("\n=== 4. ANALYTICS PAGE TEST ===")
        page.goto("http://127.0.0.1:8000/#/analytics")
        page.wait_for_selector("svg.chart")
        charts = page.query_selector_all("svg.chart")
        print(f"PASS: Analytics loaded {len(charts)} SVG charts.")
        for i, c in enumerate(charts):
            html_c = c.inner_html()
            assert "NaN" not in html_c, f"NaN found in chart {i}"
        print("PASS: All SVG charts rendered with valid coordinates and no NaN.")

        print("\n=== 5. METHODOLOGY (ABOUT) PAGE TEST ===")
        page.goto("http://127.0.0.1:8000/#/about")
        page.wait_for_selector("#eval dl.kv")
        about_text = page.inner_text("#eval")
        print("Methodology evaluation summary:")
        for line in about_text.splitlines()[:6]:
            print("  ", line)
        assert "hist gradient boosting" in about_text
        assert "11,585" in about_text
        assert "2,045" in about_text
        print("PASS: Methodology page correctly displays approved dataset counts (11,585 dev / 2,045 test).")

        print("\n=== 6. HISTORY PAGE TEST ===")
        page.goto("http://127.0.0.1:8000/#/history")
        page.wait_for_selector("table")
        history_text = page.inner_text("table")
        print("History Table row sample:", history_text.splitlines()[:3])
        assert "swift" in history_text.lower()
        print("PASS: Saved prediction appears in History.")

        # Test Clear History
        page.on("dialog", lambda dialog: dialog.accept())
        page.click("button#clear")
        page.wait_for_selector(".empty")
        print("PASS: History successfully cleared.")

        print("\n=== 7. MOBILE RESPONSIVENESS & CONSOLE ERRORS ===")
        page.set_viewport_size({"width": 375, "height": 667})
        page.goto("http://127.0.0.1:8000/#/estimate")
        page.wait_for_selector("form#f")
        scroll_w = page.evaluate("document.documentElement.scrollWidth")
        client_w = page.evaluate("document.documentElement.clientWidth")
        assert scroll_w <= client_w + 1, f"Horizontal overflow on mobile: scrollWidth={scroll_w}, clientWidth={client_w}"
        print(f"PASS: Mobile width 375px has no horizontal overflow (scrollWidth={scroll_w}, clientWidth={client_w}).")

        browser.close()

    print("\n=== FINAL BROWSER AUDIT SUMMARY ===")
    print("Console Errors Count:   ", len(console_errors))
    if console_errors:
        print("Errors:", console_errors)
    print("Failed Requests Count:  ", len(failed_requests))
    if failed_requests:
        print("Failed Requests:", failed_requests)
    assert len(console_errors) == 0, f"Unexpected console errors: {console_errors}"
    assert len(failed_requests) == 0, f"Unexpected failed requests: {failed_requests}"


def run_api_failure_audit():
    print("\n=== 8. DIRECT API FAILURE & REJECTION AUDIT ===")
    def post(url, payload):
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    # 1. Unsupported manufacturer
    status, body = post("http://127.0.0.1:8000/api/predict", {
        "make": "Tesla", "model": "Model 3", "year": 2020, "km_driven": 30000, "fuel": "Electric", "transmission": "Automatic"
    })
    assert status == 422 and body["error"]["code"] == "unsupported_vehicle" and "estimated_price_inr" not in body
    print("PASS: Unsupported manufacturer returns 422 unsupported_vehicle (no price returned).")

    # 2. Unsupported year (>2022)
    status, body = post("http://127.0.0.1:8000/api/predict", {
        "make": "Maruti Suzuki", "model": "Swift", "year": 2026, "km_driven": 30000, "fuel": "Petrol", "transmission": "Manual"
    })
    assert status == 422 and body["error"]["code"] == "year_out_of_coverage" and "estimated_price_inr" not in body
    print("PASS: Unsupported year returns 422 year_out_of_coverage (no price returned).")

    # 3. Unsupported category (Coupe)
    status, body = post("http://127.0.0.1:8000/api/predict", {
        "make": "Maruti Suzuki", "model": "Swift", "year": 2016, "km_driven": 30000, "fuel": "Petrol", "transmission": "Manual", "body_type": "Coupe"
    })
    assert status == 422 and body["error"]["code"] == "unsupported_value" and "estimated_price_inr" not in body
    print("PASS: Unsupported body type returns 422 unsupported_value (no price returned).")

    # 4. Missing required fields
    status, body = post("http://127.0.0.1:8000/api/predict", {"make": "Maruti Suzuki", "model": "Swift", "year": 2016})
    assert status == 422 and body["error"]["code"] == "validation_error" and "estimated_price_inr" not in body
    print("PASS: Missing required fields returns 422 validation_error (no price returned).")


if __name__ == "__main__":
    run_browser_audit()
    run_api_failure_audit()
