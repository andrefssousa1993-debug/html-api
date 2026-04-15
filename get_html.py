from fastapi import APIRouter, Header, Depends, HTTPException
from pydantic import BaseModel
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import os

router = APIRouter()

# -------------------------------
# LOAD API KEY
# -------------------------------
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
# REQUEST MODEL (JSON)
# -------------------------------
class RequestData(BaseModel):
    url_target: str
    url_login: str | None = None
    username: str | None = None
    password: str | None = None


# -------------------------------
# SMART FIND INPUT
# -------------------------------
def find_input(page, keywords):
    for keyword in keywords:
        locator = page.locator(f'input[name*="{keyword}"], input[id*="{keyword}"]').first
        if locator.count() > 0:
            return locator

    # fallback genérico
    locator = page.locator("input[type='text'], input[type='email']").first
    if locator.count() > 0:
        return locator

    return None


# -------------------------------
# MAIN ENDPOINT
# -------------------------------
@router.post("/get-html")
def get_html(data: RequestData, _: None = Depends(verify_api_key)):

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # =========================
            # 🔵 LOGIN (se enviado)
            # =========================
            if data.url_login and data.username and data.password:

                page.goto(data.url_login)
                page.wait_for_load_state("networkidle")

                # encontrar campos automaticamente
                user_input = find_input(page, ["user", "email", "login"])
                pass_input = page.locator("input[type='password']").first

                if not user_input:
                    raise Exception("Username field not found")

                if pass_input.count() == 0:
                    raise Exception("Password field not found")

                user_input.fill(data.username)
                pass_input.fill(data.password)

                # botão login
                login_btn = page.locator(
                    "button[type='submit'], input[type='submit']"
                ).first

                if login_btn.count() > 0:
                    login_btn.click()
                else:
                    pass_input.press("Enter")

                # esperar
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(2000)

                # validação mais robusta
                if "login" in page.url.lower():
                    raise HTTPException(status_code=403, detail="Login failed")

            # =========================
            # 🔴 TARGET PAGE
            # =========================
            page.goto(data.url_target)
            page.wait_for_load_state("networkidle")

            html = page.content()

            # detectar login obrigatório
            if "login" in page.url.lower():
                raise HTTPException(
                    status_code=403,
                    detail="Target requires login"
                )

            # detectar permissões
            if any(word in page.title().lower() for word in ["forbidden", "denied"]):
                raise HTTPException(
                    status_code=403,
                    detail="Invalid permissions"
                )

            soup = BeautifulSoup(html, "html.parser")
            body = soup.body

            browser.close()

            return {
                "status": "success",
                "body": str(body) if body else ""
            }

    except HTTPException as he:
        return {
        "status": "fail",
        "response": he.detail
    }

    except Exception as e:
        return {
        "status": "fail",
        "response": str(e)
    }