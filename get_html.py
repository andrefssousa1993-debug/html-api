from fastapi import APIRouter, Header, Depends, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import os
import re
import asyncio

router = APIRouter()

load_dotenv()
API_KEY = os.getenv("API_KEY")

# -------------------------------
# PLAYWRIGHT GLOBALS
# -------------------------------
_playwright = None
_browser = None
_startup_lock = asyncio.Lock()

_session_cache = {}


# -------------------------------
# STARTUP / SHUTDOWN
# -------------------------------
async def start_browser():
    global _playwright, _browser

    async with _startup_lock:
        if _browser:
            return

        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",  # 🔥 CRÍTICO: Evita que o Render congele por falta de memória
                "--disable-gpu",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-sync",
                "--disable-default-apps",
                "--disable-component-update",
                "--disable-features=Translate,BackForwardCache",
            ],
        )


async def stop_browser():
    global _playwright, _browser

    async with _startup_lock:
        if _browser:
            await _browser.close()
            _browser = None

        if _playwright:
            await _playwright.stop()
            _playwright = None


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
    render_wait_ms: int | None = 500
    force_login: bool | None = False


# -------------------------------
# FIND INPUT
# -------------------------------
async def find_input(page):
    # Otimizado com seletor combinado nativo para ser instantâneo
    combined_selector = (
        'input[type="email"], input[type="text"], input[name*="user" i], '
        'input[name*="email" i], input[id*="user" i], input[id*="email" i], '
        'input[placeholder*="user" i], input[placeholder*="email" i]'
    )
    
    try:
        locator = page.locator(combined_selector).first
        # Espera até 10 segundos para dar tempo ao Render de processar o JS do OutSystems
        await locator.wait_for(state="visible", timeout=10000)
        return locator
    except Exception:
        # Fallback seguro para o primeiro input editável caso mude o layout
        try:
            inputs = page.locator("input")
            for i in range(await inputs.count()):
                inp = inputs.nth(i)
                input_type = (await inp.get_attribute("type") or "text").lower()
                if input_type not in ["password", "hidden", "submit", "button", "checkbox", "radio"]:
                    if await inp.is_visible(timeout=500):
                        return inp
        except Exception:
            pass
    return None


# -------------------------------
# FIND LOGIN BUTTON
# -------------------------------
async def find_login_button(page):
    try:
        pattern = re.compile(r"login|log in|entrar|sign in|submit", re.IGNORECASE)
        btn = page.get_by_role("button", name=pattern)
        if await btn.count() > 0:
            return btn.first
    except Exception:
        pass

    try:
        text_btn = page.locator('button:has-text("log"), button:has-text("entrar"), button:has-text("sign")').first
        if await text_btn.count() > 0:
            return text_btn
    except Exception:
        pass

    submit = page.locator('input[type="submit"], button[type="submit"]').first
    try:
        if await submit.count() > 0:
            return submit
    except Exception:
        pass

    return None


# -------------------------------
# RESOURCE BLOCKING
# -------------------------------
async def block_heavy_resources(route):
    try:
        request = route.request
        if request.resource_type in ["image", "media", "font"]:
            await route.abort()
        else:
            await route.continue_()
    except Exception:
        pass


# -------------------------------
# PAGE WAIT HELPERS
# -------------------------------
async def goto_login_and_wait(page, url_login: str):
    await page.goto(url_login, wait_until="domcontentloaded", timeout=20000)
    try:
        await page.wait_for_load_state("networkidle", timeout=3000)
    except Exception:
        pass


async def goto_target_and_wait(page, url_target: str, render_wait_ms: int = 500):
    await page.goto(url_target, wait_until="domcontentloaded", timeout=20000)
    try:
        await page.wait_for_load_state("networkidle", timeout=3000)
    except Exception:
        pass

    try:
        await page.wait_for_function(
            """() => {
                const root = document.querySelector('#reactContainer') ||
                             document.querySelector('[data-reactroot]') ||
                             document.querySelector('main') ||
                             document.body;
                if (!root) return false;
                return root.querySelectorAll('*').length > 3 || (root.innerText || '').trim().length > 20;
            }""",
            timeout=5000,
        )
    except Exception:
        pass

    if render_wait_ms and render_wait_ms > 0:
        await page.wait_for_timeout(min(render_wait_ms, 3000))


# -------------------------------
# LOGIN
# -------------------------------
async def perform_login(page, data: RequestData):
    await goto_login_and_wait(page, data.url_login)

    user_input = await find_input(page)
    pass_input = page.locator("input[type='password']").first

    if not user_input:
        # Modo detetive automático se falhar no Render
        print(f"🚨 FAIIL: URL atual: {page.url} | Título: {await page.title()}")
        return {"ok": False, "reason": "Username field not found"}

    try:
        await pass_input.wait_for(state="visible", timeout=5000)
    except Exception:
        return {"ok": False, "reason": "Password field not found"}

    # 🔥 FORÇA BRUTA MELHORADA: Clica primeiro para focar e injeta via JS nativo com blur (ativa o React)
    try:
        js_fill = """(el, val) => { 
            el.focus();
            el.value = val; 
            el.dispatchEvent(new Event('input', { bubbles: true })); 
            el.dispatchEvent(new Event('change', { bubbles: true })); 
            el.blur();
        }"""
        await user_input.click(force=True)
        await user_input.evaluate(js_fill, data.username)
        
        await pass_input.click(force=True)
        await pass_input.evaluate(js_fill, data.password)
    except Exception as e:
        # Fallback clássico caso a injeção nativa falhe por algum motivo estrutural
        await user_input.fill(data.username, force=True)
        await pass_input.fill(data.password, force=True)

    login_btn = await find_login_button(page)

    try:
        if login_btn:
            await login_btn.click(timeout=5000, force=True)
        else:
            await pass_input.press("Enter")
    except Exception:
        await pass_input.press("Enter")

    try:
        await page.wait_for_url(lambda url: str(url) != data.url_login, timeout=6000)
    except Exception:
        pass

    try:
        await page.wait_for_load_state("networkidle", timeout=3000)
    except Exception:
        pass

    if "login" in page.url.lower():
        return {"ok": False, "reason": "Login failed"}

    return {"ok": True}


# -------------------------------
# INJECT METADATA
# -------------------------------
async def inject_metadata(page):
    try:
        await page.evaluate("""
            () => {
                document.querySelectorAll('input').forEach(input => {
                    if (input.inputmask && input.inputmask.opts) {
                        const mask = input.inputmask.opts.mask;
                        if (mask) input.setAttribute('data-oti-mask', mask.toString());
                    }
                    const parentSpan = input.closest('span');
                    if (parentSpan) {
                        if (parentSpan.classList.contains('input-date')) {
                            input.setAttribute('data-oti-type', 'date');
                        } else if (
                            parentSpan.classList.contains('input-number') ||
                            parentSpan.classList.contains('input-currency')
                        ) {
                            input.setAttribute('data-oti-type', 'number');
                        }
                    }
                });
            }
        """)
    except Exception as e:
        print(f"Aviso: Falha na injeção de metadados (não crítico): {e}")


# -------------------------------
# MAIN
# -------------------------------
@router.post("/get-html")
async def get_html(data: RequestData, _: None = Depends(verify_api_key)):
    global _browser

    if not _browser:
        await start_browser()

    target_url_lower = data.url_target.lower()
    context = None
    page = None

    try:
        session_key = None
        storage_state = None

        if data.url_login and data.username:
            session_key = f"{data.url_login}|{data.username}"
            if not data.force_login:
                storage_state = _session_cache.get(session_key)

        context_kwargs = {
            "ignore_https_errors": True,
            "viewport": {"width": 1366, "height": 768},
            # 🔥 CRÍTICO: Disfarça o browser no Render para a AWS do OutSystems não dar block
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        if storage_state:
            context_kwargs["storage_state"] = storage_state

        context = await _browser.new_context(**context_kwargs)
        await context.route("**/*", block_heavy_resources)

        page = await context.new_page()
        page.set_default_timeout(10000)
        page.set_default_navigation_timeout(20000)

        render_wait = data.render_wait_ms if data.render_wait_ms is not None else 500
        has_cached_session = storage_state is not None

        # =========================
        # FLUXO PRINCIPAL
        # =========================
        if data.url_login and data.username and data.password:
            if has_cached_session and not data.force_login:
                await goto_target_and_wait(page, data.url_target, render_wait)
                try:
                    password_count = await page.locator("input[type='password']").count()
                except Exception:
                    password_count = 0
                needs_login = ("login" in page.url.lower() or password_count > 0)
            else:
                needs_login = True
        else:
            await goto_target_and_wait(page, data.url_target, render_wait)
            needs_login = False

        # =========================
        # LOGIN SE NECESSÁRIO
        # =========================
        if needs_login:
            login_result = await perform_login(page, data)

            if not login_result["ok"]:
                return {
                    "status": "fail",
                    "response": login_result["reason"],
                }

            if session_key:
                try:
                    _session_cache[session_key] = await context.storage_state()
                except Exception as e:
                    print(f"Aviso: não foi possível guardar sessão: {e}")

            await goto_target_and_wait(page, data.url_target, render_wait)

        # =========================
        # INJEÇÃO DE METADADOS
        # =========================
        await inject_metadata(page)

        if "login" in page.url.lower():
            try:
                await page.get_by_role("link", name="Games").click(timeout=3000, force=True)
                await goto_target_and_wait(page, data.url_target, render_wait)
            except Exception:
                pass

        # =========================
        # RESULT
        # =========================
        html = await page.content()
        current_url = page.url.lower()

        if "login" in current_url and "login" not in target_url_lower:
            return {
                "status": "fail",
                "response": "Target requires login (Redirected)",
                "final_url": page.url,
            }

        try:
            password_visible = await page.locator("input[type='password']").is_visible(timeout=500)
            if password_visible and "login" not in target_url_lower:
                return {
                    "status": "fail",
                    "response": "Target requires login (Password field detected)",
                    "final_url": page.url,
                }
        except Exception:
            pass

        error_keywords = ["not enough permissions", "invalid role", "access denied", "sem permissões", "acesso negado"]
        if any(msg in html.lower() for msg in error_keywords):
            return {
                "status": "fail",
                "response": "Insufficient permissions or missing role",
                "final_url": page.url,
            }

        soup = BeautifulSoup(html, "html.parser")
        body = soup.body
        response_html = body.prettify() if body else soup.prettify()

        return {
            "status": "success",
            "response": response_html if body else "",
            "final_url": page.url,
        }

    except Exception as e:
        return {
            "status": "fail",
            "response": str(e),
        }

    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass
        if context:
            try:
                await context.close()
            except Exception:
                pass