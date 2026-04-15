from fastapi import APIRouter, Header, Depends, HTTPException
from pydantic import BaseModel
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import os

router = APIRouter()

load_dotenv()
API_KEY = os.getenv("API_KEY")

# -------------------------------
# AUTH
# -------------------------------
def verify_api_key(x_api_key: str = Header(None)):
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API key not configured")

    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")

# -------------------------------
# REQUEST MODEL
# -------------------------------
class RequestData(BaseModel):
    url_target: str
    url_login: str | None = None
    username: str | None = None
    password: str | None = None

# -------------------------------
# FIND INPUT
# -------------------------------
def find_input(page):
    selectors = [
        'input[type="email"]',
        'input[type="text"]',
        'input[name*="user"]',
        'input[name*="email"]',
        'input[id*="user"]',
        'input[id*="email"]',
        'input[placeholder*="user"]',
        'input[placeholder*="email"]'
    ]

    for sel in selectors:
        locator = page.locator(sel).first
        if locator.count() > 0 and locator.is_visible():
            return locator

    return None

# -------------------------------
# FIND LOGIN BUTTON (FORTE)
# -------------------------------
def find_login_button(page):
    possible_names = ["login", "log in", "entrar", "sign in", "submit"]

    # tentativa 1 (melhor)
    for name in possible_names:
        btn = page.get_by_role("button", name=name, exact=False)
        if btn.count() > 0:
            return btn.first

    # tentativa 2
    buttons = page.locator("button")
    for i in range(buttons.count()):
        text = buttons.nth(i).inner_text().lower()
        if any(word in text for word in ["log", "entrar", "sign"]):
            return buttons.nth(i)

    # tentativa 3
    submit = page.locator('input[type="submit"], button[type="submit"]').first
    if submit.count() > 0:
        return submit

    return None

# -------------------------------
# MAIN
# -------------------------------
@router.post("/get-html")
def get_html(data: RequestData, _: None = Depends(verify_api_key)):

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # =========================
            # LOGIN
            # =========================
            if data.url_login and data.username and data.password:

                page.goto(data.url_login)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1500)

                user_input = find_input(page)
                pass_input = page.locator("input[type='password']").first

                if not user_input:
                    return {"status": "fail", "response": "Username field not found"}

                if pass_input.count() == 0:
                    return {"status": "fail", "response": "Password field not found"}

                user_input.fill(data.username)
                pass_input.fill(data.password)

                login_btn = find_login_button(page)

                if login_btn:
                    login_btn.click()
                else:
                    pass_input.press("Enter")

                # esperar mudança real
                try:
                    page.wait_for_function(
                        f"window.location.href !== '{data.url_login}'",
                        timeout=5000
                    )
                except:
                    pass

                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1500)

                # validação robusta
                if "login" in page.url.lower():
                    return {"status": "fail", "response": "Login failed"}

            # =========================
            # TARGET
            # =========================
            page.goto(data.url_target)
            page.wait_for_load_state("networkidle")

            html = page.content()

            if "login" in page.url.lower():
                return {"status": "fail", "response": "Target requires login"}

            soup = BeautifulSoup(html, "html.parser")
            body = soup.body

            browser.close()

            return {
                "status": "success",
                "response": str(body) if body else ""
            }

    except Exception as e:
        return {
            "status": "fail",
            "response": str(e)
        }