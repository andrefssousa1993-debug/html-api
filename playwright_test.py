from playwright.sync_api import sync_playwright

def extract_html():

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)

        page = browser.new_page()

        page.goto("https://example.com")

        html = page.content()

        browser.close()

        return html


result = extract_html()

print("HTML extraido:")
print(result[:500])