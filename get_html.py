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
# FIND LOGIN BUTTON
# -------------------------------
def find_login_button(page):
    possible_names = ["login", "log in", "entrar", "sign in", "submit"]

    for name in possible_names:
        btn = page.get_by_role("button", name=name, exact=False)
        if btn.count() > 0:
            return btn.first

    buttons = page.locator("button")
    for i in range(buttons.count()):
        text = buttons.nth(i).inner_text().lower()
        if any(word in text for word in ["log", "entrar", "sign"]):
            return buttons.nth(i)

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

                # 🔥 esperar redirect real
                try:
                    page.wait_for_function(
                        f"window.location.href !== '{data.url_login}'",
                        timeout=7000
                    )
                except:
                    pass

                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(2000)

                print("URL depois do login:", page.url)

                if "login" in page.url.lower():
                    return {"status": "fail", "response": "Login failed"}

            # =========================
            # TARGET
            # =========================
            page.goto(data.url_target)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)

            print("URL depois do target:", page.url)

            # --- INJEÇÃO DE METADADOS (Segura e sem quebras) ---
            try:
                page.evaluate("""() => {
                    document.querySelectorAll('input').forEach(input => {
                        // 1. Detetar Máscaras (Inputmask.js / OutSystems)
                        if (input.inputmask && input.inputmask.opts) {
                            const mask = input.inputmask.opts.mask;
                            if (mask) input.setAttribute('data-oti-mask', mask.toString());
                        }

                        // 2. Detetar tipos reais (Hierarchy Check)
                        const parentSpan = input.closest('span');
                        if (parentSpan) {
                            if (parentSpan.classList.contains('input-date')) {
                                input.setAttribute('data-oti-type', 'date');
                            } else if (parentSpan.classList.contains('input-number') || parentSpan.classList.contains('input-currency')) {
                                input.setAttribute('data-oti-type', 'number');
                            }
                        }
                    });
                }""")
            except Exception as e:
                print(f"Aviso: Falha na injeção de metadados (não crítico): {e}")

            # fallback (SPA / OutSystems)
            if "login" in page.url.lower():
                print("Fallback: tentar navegação interna")

                try:
                    page.get_by_role("link", name="Games").click()
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(1500)
                except:
                    pass

            # =========================
            # RESULT
            # =========================
            html = page.content()
            current_url = page.url.lower()
            if "login" in current_url and "login" not in target_url_lower:
                return {"status": "fail", "response": "Target requires login (Redirected)"}

# Opcional: Verificar se existe um campo de password visível que não deveria estar lá
            if page.locator("input[type='password']").is_visible() and "login" not in target_url_lower:
                return {"status": "fail", "response": "Target requires login (Password field detected)"}
            
            error_keywords = ["not enough permissions", "invalid role", "access denied", "sem permissões", "acesso negado"]
            if any(msg in html.lower() for msg in error_keywords):
                return {"status": "fail", "response": "Insufficient permissions or missing role"}

            soup = BeautifulSoup(html, "html.parser")
            body = soup.body

            response_html = body.prettify() if body else soup.prettify()

            browser.close()

            return {
                "status": "success",
                "response": response_html if body else ""
            }

    except Exception as e:
        return {
            "status": "fail",
            "response": str(e)
        }