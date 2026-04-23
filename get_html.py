from fastapi import APIRouter, Header, Depends, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import os
import re
import time

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
async def find_input(page):
    combined_selector = (
        'input[type="email"], input[type="text"], input[name*="user"], '
        'input[name*="email"], input[id*="user"], input[id*="email"], '
        'input[placeholder*="user"], input[placeholder*="email"]'
    )
    
    locator = page.locator(combined_selector).first
    try:
        await locator.wait_for(state="visible", timeout=3000)
        return locator
    except:
        return None

# -------------------------------
# FIND LOGIN BUTTON
# -------------------------------
async def find_login_button(page):
    pattern = re.compile(r"login|log in|entrar|sign in|submit", re.IGNORECASE)
    btn = page.get_by_role("button", name=pattern)
    if await btn.count() > 0:
        return btn.first

    text_btn = page.locator('button:has-text("log"), button:has-text("entrar"), button:has-text("sign")')
    if await text_btn.count() > 0:
        return text_btn.first

    submit = page.locator('input[type="submit"], button[type="submit"]')
    if await submit.count() > 0:
        return submit.first

    return None

# -------------------------------
# MAIN
# -------------------------------
@router.post("/get-html")
async def get_html(data: RequestData, _: None = Depends(verify_api_key)):
    target_url_lower = data.url_target.lower()
    total_start = time.time()
    
    try:
        async with async_playwright() as p:
            print("\n--- INÍCIO DO REQUEST ---")
            step_time = time.time()
            browser = await p.chromium.launch(headless=True)
            
            # Injetar um User-Agent real
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            
            # 🔥 REMOVIDO: O bloqueio de imagens foi desativado porque o OutSystems 
            # encrava se não conseguir carregar certos assets visuais na página de login.
            # await context.route("**/*", lambda route: route.continue_() if route.request.resource_type not in ["image", "font", "media"] else route.abort())
            
            page = await context.new_page()
            print(f"[Cronómetro] Abrir Browser: {time.time() - step_time:.2f}s")

            # =========================
            # LOGIN
            # =========================
            if data.url_login and data.username and data.password:
                step_time = time.time()
                
                try:
                    await page.goto(data.url_login, wait_until="domcontentloaded", timeout=15000)
                except Exception as e:
                    print(f"Aviso: goto login excedeu tempo ou falhou. A tentar continuar... Erro: {e}")
                print(f"[Cronómetro] Goto Login ({data.url_login}): {time.time() - step_time:.2f}s")

                user_input = await find_input(page)
                pass_input = page.locator("input[type='password']").first

                if not user_input:
                    return {"status": "fail", "response": "Username field not found"}

                if await pass_input.count() == 0:
                    return {"status": "fail", "response": "Password field not found"}

                # 🔥 SOLUÇÃO: Preenchimento forçado (ignora animações e overlays transparentes do OutSystems)
                await user_input.fill(data.username, force=True)
                await pass_input.fill(data.password, force=True)

                login_btn = await find_login_button(page)

                step_time = time.time()
                try:
                    if login_btn:
                        await login_btn.click(timeout=5000, force=True) # force=True aqui também por segurança
                    else:
                        await pass_input.press("Enter")
                except Exception as e:
                    print(f"Aviso: Falha ao clicar no botão de login: {e}")
                print(f"[Cronómetro] Clicar Login: {time.time() - step_time:.2f}s")

                step_time = time.time()
                try:
                    await page.wait_for_url(lambda url: url != data.url_login, timeout=5000)
                except:
                    pass
                print(f"[Cronómetro] Esperar Redirect: {time.time() - step_time:.2f}s")

                if "login" in page.url.lower():
                    return {"status": "fail", "response": "Login failed"}

            # =========================
            # TARGET
            # =========================
            step_time = time.time()
            try:
                await page.goto(data.url_target, wait_until="domcontentloaded", timeout=15000)
            except Exception as e:
                print(f"Aviso: goto target excedeu tempo ou falhou. Erro: {e}")
            print(f"[Cronómetro] Goto Target ({data.url_target}): {time.time() - step_time:.2f}s")
            
            try:
                await page.wait_for_load_state("networkidle", timeout=2000)
            except:
                pass

            # --- INJEÇÃO DE METADADOS ---
            try:
                await page.evaluate("""() => {
                    document.querySelectorAll('input').forEach(input => {
                        if (input.inputmask && input.inputmask.opts) {
                            const mask = input.inputmask.opts.mask;
                            if (mask) input.setAttribute('data-oti-mask', mask.toString());
                        }
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
                print(f"Aviso: Falha na injeção de metadados: {e}")

            # fallback (SPA / OutSystems)
            if "login" in page.url.lower():
                print("Fallback: tentar navegação interna")
                step_time = time.time()
                try:
                    game_link = page.get_by_role("link", name="Games")
                    await game_link.click(timeout=3000, force=True)
                    await page.wait_for_load_state("networkidle", timeout=2000)
                except Exception as e:
                    print(f"Aviso: Fallback link click falhou: {e}")
                print(f"[Cronómetro] Fallback Link Click: {time.time() - step_time:.2f}s")

            # =========================
            # RESULT
            # =========================
            step_time = time.time()
            html = await page.content()
            current_url = page.url.lower()
            
            if "login" in current_url and "login" not in target_url_lower:
                return {"status": "fail", "response": "Target requires login (Redirected)"}

            pass_visible = await page.locator("input[type='password']").is_visible()
            if pass_visible and "login" not in target_url_lower:
                return {"status": "fail", "response": "Target requires login (Password field detected)"}
            
            error_keywords = ["not enough permissions", "invalid role", "access denied", "sem permissões", "acesso negado"]
            if any(msg in html.lower() for msg in error_keywords):
                return {"status": "fail", "response": "Insufficient permissions or missing role"}

            soup = BeautifulSoup(html, "html.parser")
            body = soup.body

            response_html = body.prettify() if body else soup.prettify()

            await browser.close()
            print(f"[Cronómetro] Parsing e Fecho do Browser: {time.time() - step_time:.2f}s")
            print(f"--- FIM DO REQUEST (Tempo Total: {time.time() - total_start:.2f}s) ---\n")

            return {
                "status": "success",
                "response": response_html if body else ""
            }

    except Exception as e:
        print(f"ERRO CRÍTICO: {e}")
        return {
            "status": "fail",
            "response": str(e)
        }