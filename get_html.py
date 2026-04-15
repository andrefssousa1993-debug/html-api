from fastapi import APIRouter, Header, Depends, HTTPException
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional
import os

router = APIRouter()

# -------------------------------
# LOAD API KEY
# -------------------------------
load_dotenv()
API_KEY = os.getenv("API_KEY")


# -------------------------------
# AUTH MIDDLEWARE
# -------------------------------
def verify_api_key(x_api_key: str = Header(None)):
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API key not configured")

    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")


# -------------------------------
# REQUEST MODEL (JSON)
# -------------------------------
class GetHtmlRequest(BaseModel):
    url_target: str
    url_login: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


# -------------------------------
# SAFE NORMALIZATION
# -------------------------------
def safe_lower(value):
    if callable(value):
        value = value()
    return str(value).lower() if value is not None else ""


# -------------------------------
# MAIN ENDPOINT (JSON)
# -------------------------------
@router.post("/get-html")
def get_html_with_optional_login(
    data: GetHtmlRequest,
    _: None = Depends(verify_api_key)
):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # =========================
            # 🔵 LOGIN (se credenciais enviadas)
            # =========================
            if data.username and data.password:

                page.goto(data.url_login or data.url_target)
                page.wait_for_load_state("networkidle")

                # USERNAME
                user_input = page.locator(
                'input#username, input[name="username"], input[type="text"]'
                ).first

                if user_input.count() == 0:
                    raise Exception("Username field not found")

                user_input.fill(data.username)

                # PASSWORD
                pass_input = page.locator(
                'input#password, input[type="password"]'
                ).first

                if pass_input.count() == 0:
                    raise Exception("Password field not found")

                pass_input.fill(data.password)

                # LOGIN BUTTON
                login_btn = page.locator(
                    'button[type="submit"], input[type="submit"]'
                ).first

                if login_btn.count() > 0:
                    login_btn.click()
                else:
                    pass_input.press("Enter")

                page.wait_for_load_state("networkidle")

                # ❌ LOGIN FAILED
                if "login" in safe_lower(page.url) or "login" in safe_lower(page.title):
                    raise HTTPException(status_code=403, detail="Login failed")

            # =========================
            # 🔴 TARGET PAGE
            # =========================
            page.goto(data.url_target)
            page.wait_for_load_state("networkidle")

            url = safe_lower(page.url)
            title = safe_lower(page.title)
            html = page.content()

            # ❌ TARGET REQUIRES LOGIN
            if "login" in url or "login" in title:
                raise HTTPException(
                    status_code=403,
                    detail="Target requires login"
                )

            # ❌ INVALID PERMISSIONS
            if (
                "forbidden" in url or
                "access denied" in title or
                "permission" in title
            ):
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
        raise he

    except Exception as e:
        return {
            "status": "fail",
            "error": str(e)
        }