from fastapi import APIRouter, Header, Depends, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import os
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

# Guarda sessões por login+user
# Exemplo chave: "https://site/login|user@email.com"
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
                "--disable-dev-shm-usage",
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

    # Espera extra depois do load/render.
    # Reduzido para acelerar. Se vier HTML vazio, envia render_wait_ms maior no payload.
    render_wait_ms: int | None = 500

    # Forçar novo login, ignorando sessão guardada.
    force_login: bool | None = False


# -------------------------------
# FIND INPUT
# -------------------------------
async def find_input(page):
    selectors = [
        'input[type="email"]',
        'input[type="text"]',
        'input:not([type])',
        'input[name*="user" i]',
        'input[name*="email" i]',
        'input[name*="login" i]',
        'input[name*="username" i]',
        'input[name*="utilizador" i]',
        'input[id*="user" i]',
        'input[id*="email" i]',
        'input[id*="login" i]',
        'input[id*="username" i]',
        'input[id*="utilizador" i]',
        'input[placeholder*="user" i]',
        'input[placeholder*="email" i]',
        'input[placeholder*="login" i]',
        'input[placeholder*="username" i]',
        'input[placeholder*="utilizador" i]',
    ]

    try:
        await page.wait_for_selector("input", timeout=8000)
    except Exception:
        pass

    for sel in selectors:
        locator = page.locator(sel).first

        try:
            if await locator.count() > 0 and await locator.is_visible(timeout=700):
                return locator
        except Exception:
            pass

    # Fallback: primeiro input visível que não seja password/hidden/submit/button
    inputs = page.locator("input")

    try:
        count = await inputs.count()
    except Exception:
        count = 0

    for i in range(count):
        inp = inputs.nth(i)

        try:
            input_type = (await inp.get_attribute("type") or "text").lower()

            if input_type in ["password", "hidden", "submit", "button", "checkbox", "radio"]:
                continue

            if await inp.is_visible(timeout=500):
                return inp
        except Exception:
            pass

    return None


# -------------------------------
# FIND LOGIN BUTTON
# -------------------------------
async def find_login_button(page):
    possible_names = ["login", "log in", "entrar", "sign in", "submit"]

    for name in possible_names:
        btn = page.get_by_role("button", name=name, exact=False)

        try:
            if await btn.count() > 0 and await btn.first.is_visible(timeout=500):
                return btn.first
        except Exception:
            pass

    buttons = page.locator("button")

    try:
        count = await buttons.count()
    except Exception:
        count = 0

    for i in range(count):
        button = buttons.nth(i)

        try:
            text = (await button.inner_text(timeout=500)).lower()

            if any(word in text for word in ["log", "entrar", "sign", "submit"]):
                return button
        except Exception:
            pass

    submit = page.locator('input[type="submit"], button[type="submit"]').first

    try:
        if await submit.count() > 0 and await submit.is_visible(timeout=500):
            return submit
    except Exception:
        pass

    return None


# -------------------------------
# RESOURCE BLOCKING
# -------------------------------
async def block_heavy_resources(route):
    request = route.request

    # Não bloquear script nem stylesheet.
    # OutSystems/React precisa deles para renderizar o HTML real.
    if request.resource_type in ["image", "media", "font"]:
        await route.abort()
    else:
        await route.continue_()


# -------------------------------
# PAGE WAIT HELPERS
# -------------------------------
async def goto_login_and_wait(page, url_login: str):
    await page.goto(url_login, wait_until="load", timeout=20000)

    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass

    await page.wait_for_timeout(500)


async def goto_target_and_wait(page, url_target: str, render_wait_ms: int = 500):
    await page.goto(url_target, wait_until="load", timeout=20000)

    # Mais curto para não ficar preso em polling/requests de SPA.
    try:
        await page.wait_for_load_state("networkidle", timeout=4000)
    except Exception:
        pass

    # OutSystems/React: esperar o root deixar de estar vazio.
    try:
        await page.wait_for_function(
            """() => {
                const root =
                    document.querySelector('#reactContainer') ||
                    document.querySelector('[data-reactroot]') ||
                    document.querySelector('main') ||
                    document.body;

                if (!root) return false;

                const text = (root.innerText || '').trim();
                const hasElements = root.querySelectorAll('*').length > 3;

                return hasElements || text.length > 20;
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
        return {"ok": False, "reason": "Username field not found"}

    if await pass_input.count() == 0:
        return {"ok": False, "reason": "Password field not found"}

    await user_input.fill(data.username)
    await pass_input.fill(data.password)

    login_btn = await find_login_button(page)

    if login_btn:
        await login_btn.click()
    else:
        await pass_input.press("Enter")

    # Esperar redirect real, mas sem bloquear demasiado.
    try:
        await page.wait_for_url(
            lambda url: str(url) != data.url_login,
            timeout=8000,
        )
    except PlaywrightTimeoutError:
        pass
    except Exception:
        pass

    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass

    await page.wait_for_timeout(800)

    print("URL depois do login:", page.url)

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
                    // 1. Detetar máscaras Inputmask.js / OutSystems
                    if (input.inputmask && input.inputmask.opts) {
                        const mask = input.inputmask.opts.mask;
                        if (mask) input.setAttribute('data-oti-mask', mask.toString());
                    }

                    // 2. Detetar tipos reais por classes de parent
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
                # Tenta target com sessão guardada
                await goto_target_and_wait(page, data.url_target, render_wait)

                password_count = await page.locator("input[type='password']").count()

                needs_login = (
                    "login" in page.url.lower()
                    or password_count > 0
                )
            else:
                # Sem sessão: faz login primeiro, como no código antigo
                needs_login = True
        else:
            # Sem dados de login: abre target diretamente
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

            # Guardar sessão depois de login bem-sucedido
            if session_key:
                try:
                    _session_cache[session_key] = await context.storage_state()
                except Exception as e:
                    print(f"Aviso: não foi possível guardar sessão: {e}")

            # Ir ao target já autenticado
            await goto_target_and_wait(page, data.url_target, render_wait)

        print("URL depois do target:", page.url)

        # =========================
        # INJEÇÃO DE METADADOS
        # =========================
        await inject_metadata(page)

        # Fallback antigo SPA / OutSystems
        if "login" in page.url.lower():
            print("Fallback: tentar navegação interna")

            try:
                await page.get_by_role("link", name="Games").click(timeout=3000)
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

        error_keywords = [
            "not enough permissions",
            "invalid role",
            "access denied",
            "sem permissões",
            "acesso negado",
        ]

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