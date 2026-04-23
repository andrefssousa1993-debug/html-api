from fastapi import FastAPI, Form
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

app = FastAPI()

from get_html import router as html_router
app.include_router(html_router)

# -------------------------------
# Funções internas
# -------------------------------

def extract_html(url: str) -> str:
    """Extrai o HTML completo da página."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url)
        html = page.content()
        browser.close()
        return html

def extract_body(url: str) -> str:
    """Extrai apenas o <body> da página."""
    full_html = extract_html(url)
    soup = BeautifulSoup(full_html, "html.parser")
    body = soup.body
    return str(body) if body else ""

def auto_login_and_navigate(url_login: str, username: str, password: str, url_target: str) -> str:
    """
    Faz login automático detectando os campos de username/email, senha e botão de login,
    depois navega para url_target e retorna o <body>.
    """
    from bs4 import BeautifulSoup
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # ------------------- LOGIN -------------------
        login_result = []

        try:
            page.goto(url_login)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1500)

            # ---------- USERNAME ----------
            user_input = page.locator(
                'input[type="email"], input[type="text"], '
                'input[name*="user"], input[name*="email"], '
                'input[id*="user"], input[id*="email"], '
                'input[placeholder*="user"], input[placeholder*="email"]'
            ).first

            if not user_input.is_visible():
                raise Exception("Campo de username/email não encontrado")
            user_input.fill(username)
            login_result.append({"element": "username", "type": "text", "test": "fill_input", "value": username, "status": "ok"})

            # ---------- PASSWORD ----------
            pass_input = page.locator(
                'input[type="password"], input[name*="pass"], input[name*="senha"], '
                'input[id*="pass"], input[id*="senha"], input[placeholder*="pass"], input[placeholder*="senha"]'
            ).first

            if not pass_input.is_visible():
                raise Exception("Campo de password não encontrado")
            pass_input.fill(password)
            login_result.append({"element": "password", "type": "password", "test": "fill_input", "value": password, "status": "ok"})

            # ---------- LOGIN BUTTON ----------
            login_btn = None
            possible_names = ["login", "log in", "entrar", "sign in", "submit"]

            for name in possible_names:
                btn = page.get_by_role("button", name=name, exact=False)
                if btn.count() > 0:
                    login_btn = btn.first
                    break

            if not login_btn:
                buttons = page.locator("button")
                for i in range(buttons.count()):
                    text = buttons.nth(i).inner_text().lower()
                    if "log" in text or "entrar" in text or "sign" in text:
                        login_btn = buttons.nth(i)
                        break

            if not login_btn:
                submit = page.locator('input[type="submit"], button[type="submit"]').first
                if submit.is_visible():
                    login_btn = submit

            if not login_btn:
                raise Exception("Botão de login não encontrado")

            # ---------- Tenta Enter ou Click ----------
            try:
                pass_input.press("Enter")
            except:
                login_btn.click()

            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1000)

            # ---------- VERIFICA SE LOGIN FALHOU ----------
            current_url = page.url
            current_title = page.title()
            if "login" in current_title.lower() or "login" in current_url.lower():
                raise Exception("Login falhou — ainda na página de login.")

            login_result.append({"element": "login_button", "type": "button", "test": "click", "value": None, "status": "ok"})

        except Exception as e:
            browser.close()
            raise Exception(f"Erro no login: {str(e)}")

        # ------------------- Navega para a página alvo -------------------
        page.goto(url_target)
        page.wait_for_load_state("networkidle")

        # ------------------- Pega o body -------------------
        html = page.content()
        browser.close()
        soup = BeautifulSoup(html, "html.parser")
        body = soup.body
        return str(body) if body else ""
    
def run_regression_test(page):
    results = []

    SUBMIT_KEYWORDS = {"save", "submit", "guardar", "gravar", "enviar", "confirm", "ok", "apply", "login", "entrar", "sign in", "log in"}

    # -------- INPUTS --------
    inputs = page.query_selector_all("input")
    for inp in inputs:
        name = inp.get_attribute("name") or inp.get_attribute("id") or "input"
        input_type = inp.get_attribute("type") or "text"
        try:
            if input_type in ["text", "email", "password"]:
                inp.fill("TestValue")
                results.append({
                    "element": name,
                    "type": input_type,
                    "test": "fill_input",
                    "value": "TestValue",
                    "status": "ok"
                })
            elif input_type == "checkbox":
                inp.check()
                results.append({
                    "element": name,
                    "type": "checkbox",
                    "test": "check",
                    "value": True,
                    "status": "ok"
                })
            elif input_type == "radio":
                inp.check()
                results.append({
                    "element": name,
                    "type": "radio",
                    "test": "select_radio",
                    "value": True,
                    "status": "ok"
                })
        except Exception as e:
            results.append({
                "element": name,
                "type": input_type,
                "test": "input_action",
                "value": None,
                "status": "fail",
                "error": str(e)
            })

    # -------- TEXTAREA --------
    textareas = page.query_selector_all("textarea")
    for area in textareas:
        name = area.get_attribute("name") or area.get_attribute("id") or "textarea"
        try:
            area.fill("Test textarea value")
            results.append({
                "element": name,
                "type": "textarea",
                "test": "fill_textarea",
                "value": "Test textarea value",
                "status": "ok"
            })
        except Exception as e:
            results.append({
                "element": name,
                "type": "textarea",
                "test": "fill_textarea",
                "value": None,
                "status": "fail",
                "error": str(e)
            })

    # -------- SELECT --------
    selects = page.query_selector_all("select")
    for sel in selects:
        name = sel.get_attribute("name") or sel.get_attribute("id") or "select"
        try:
            options = sel.query_selector_all("option")
            if options:
                value = options[0].get_attribute("value")
                sel.select_option(value)
                results.append({
                    "element": name,
                    "type": "select",
                    "test": "select_option",
                    "value": value,
                    "status": "ok"
                })
        except Exception as e:
            results.append({
                "element": name,
                "type": "select",
                "test": "select_option",
                "value": None,
                "status": "fail",
                "error": str(e)
            })

    # -------- BUTTONS --------
    buttons = page.query_selector_all("button")
    for btn in buttons:
        label = (btn.inner_text() or "").strip()
        btn_type = (btn.get_attribute("type") or "").lower()

        inside_form = btn.evaluate("el => !!el.closest('form')")
        is_submit_type = btn_type == "submit"
        is_submit_text = any(kw in label.lower() for kw in SUBMIT_KEYWORDS)

        if not inside_form or (not is_submit_type and not is_submit_text):
            results.append({
                "element": label or "button",
                "type": "button",
                "test": "click_skipped",
                "value": None,
                "status": "skipped",
                "reason": "not inside form or not a submit/save button"
            })
            continue

        try:
            btn.click()
            results.append({
                "element": label or "button",
                "type": "button",
                "test": "click",
                "value": None,
                "status": "ok"
            })
        except Exception as e:
            results.append({
                "element": label or "button",
                "type": "button",
                "test": "click",
                "value": None,
                "status": "fail",
                "error": str(e)
            })

    # -------- LINKS --------
    links = page.query_selector_all("a")
    for link in links:
        label = (link.inner_text() or "").strip()
        href = link.get_attribute("href") or ""
        results.append({
            "element": label or "link",
            "type": "link",
            "test": "detected",
            "value": href,
            "status": "skipped",
            "reason": "links are not clicked in regression tests"
        })

    return results


# -------------------------------
# Rotas da API
# -------------------------------

def smart_login(page, username: str, password: str):

    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)

    # USERNAME
    username_input = page.locator(
        'input[type="email"], input[type="text"], input[name*="user"], input[name*="email"], input[id*="user"], input[id*="email"]'
    ).first

    if username_input.count() == 0:
        raise Exception("Campo de username/email não encontrado")

    username_input.fill(username)

    # PASSWORD
    password_input = page.locator('input[type="password"]').first

    if password_input.count() == 0:
        raise Exception("Campo de password não encontrado")

    password_input.fill(password)

    # LOGIN BUTTON
    login_btn = None

    possible_names = ["login","log in","entrar","sign in","submit"]

    for name in possible_names:
        btn = page.get_by_role("button", name=name, exact=False)
        if btn.count() > 0:
            login_btn = btn.first
            break

    if not login_btn:
        buttons = page.locator("button")
        for i in range(buttons.count()):
            text = buttons.nth(i).inner_text().lower()
            if "log" in text or "entrar" in text or "sign" in text:
                login_btn = buttons.nth(i)
                break

    if not login_btn:
        raise Exception("Botão de login não encontrado")

    login_btn.click()

    page.wait_for_load_state("networkidle")

@app.get("/extract-html")
def get_html(url: str):
    html = extract_html(url)
    return {"status": "success", "html": html}

@app.get("/extract-body")
def get_body(url: str):
    body = extract_body(url)
    return {"status": "success", "body": body}

@app.get("/test-page")
def test_page(url: str):
    body = extract_body(url)
    return {
        "status": "success",
        "message": f"Página acessada com sucesso! Tamanho do body: {len(body)} caracteres."
    }

@app.post("/auto-login")
def auto_login(
    url_login: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    url_target: str = Form(...)
):
    body = auto_login_and_navigate(url_login, username, password, url_target)
    return {"status": "success", "body": body}

@app.post("/regression-test")
def regression_test(
    url_target: str = Form(...),
    url_login: str = Form(None),
    username: str = Form(None),
    password: str = Form(None)
):
    response = {"status": "success", "login": None, "target": None}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # ------------------- LOGIN -------------------
        if url_login and username and password:
            login_result = []

            try:
                page.goto(url_login)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1500)

                # ---------- USERNAME ----------
                user_input = page.locator(
                    'input[type="email"], input[type="text"], '
                    'input[name*="user"], input[name*="email"], '
                    'input[id*="user"], input[id*="email"], '
                    'input[placeholder*="user"], input[placeholder*="email"]'
                ).first

                if not user_input.is_visible():
                    raise Exception("Campo de username/email não encontrado")

                user_input.fill(username)
                login_result.append({"element": "username", "type": "text", "test": "fill_input", "value": username, "status": "ok"})

                # ---------- PASSWORD ----------
                pass_input = page.locator('input[type="password"]').first

                if not pass_input.is_visible():
                    raise Exception("Campo de password não encontrado")

                pass_input.fill(password)
                login_result.append({"element": "password", "type": "password", "test": "fill_input", "value": password, "status": "ok"})

                # ---------- LOGIN BUTTON ----------
                login_btn = None
                possible_names = ["login", "log in", "entrar", "sign in", "submit"]

                for name in possible_names:
                    btn = page.get_by_role("button", name=name, exact=False)
                    if btn.count() > 0:
                        login_btn = btn.first
                        break

                if not login_btn:
                    buttons = page.locator("button")
                    for i in range(buttons.count()):
                        text = buttons.nth(i).inner_text().lower()
                        if "log" in text or "entrar" in text or "sign" in text:
                            login_btn = buttons.nth(i)
                            break

                if not login_btn:
                    submit = page.locator('input[type="submit"], button[type="submit"]').first
                    if submit.is_visible():
                        login_btn = submit

                if not login_btn:
                    response["status"] = "fail"
                    response["login"] = {"url": url_login, "tests": login_result, "error": "Botão de login não encontrado."}
                    browser.close()
                    return response

                # Screenshot antes (debug - podes remover depois)
                page.screenshot(path="before_login.png")

                if login_btn:
                    login_btn.click()
                else:
                    pass_input.press("Enter")

                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1000)

                # Screenshot depois (debug - podes remover depois)
                page.screenshot(path="after_login.png")

                print("URL antes do login:", url_login)
                print("URL depois do login:", page.url)
                print("Title da página:", page.title())
                # ---------- VERIFICA SE LOGIN FALHOU ----------
                # ---------- VERIFICA SE LOGIN FALHOU ----------
                # Espera até a URL mudar OU timeout de 5 segundos
                try:
                    page.wait_for_function(
                        f"window.location.href !== '{url_login}'",
                        timeout=5000
                    )
                except:
                    pass  # se não mudar em 5s, continua e verifica o título

                page.wait_for_timeout(1000)

                current_url = page.url
                current_title = page.title()

                print("URL final:", current_url)
                print("Title final:", current_title)

                # Se ainda está na página de Login pelo título
                if "login" in current_title.lower() or "login" in current_url.lower():
                    response["status"] = "fail"
                    response["login"] = {"url": url_login, "tests": login_result, "error": "Login falhou — ainda na página de login."}
                    browser.close()
                    return response

                login_result.append({"element": "login_button", "type": "button", "test": "click", "value": None, "status": "ok"})
                response["login"] = {"url": url_login, "tests": login_result}


            except Exception as e:
                response["status"] = "fail"
                response["login"] = {"url": url_login, "tests": login_result, "error": str(e)}
                browser.close()
                return response

        # ------------------- TARGET -------------------
        try:
            page.goto(url_target)
            page.wait_for_load_state("networkidle")

            target_tests = run_regression_test(page)

            response["target"] = {
                "url": url_target,
                "tests": target_tests
            }

        except Exception as e:
            response["status"] = "fail"
            response["target"] = {
                "url": url_target,
                "tests": [],
                "error": str(e)
            }

        browser.close()
        return response
# -------------------------------
# python main.py
# -------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=10000)