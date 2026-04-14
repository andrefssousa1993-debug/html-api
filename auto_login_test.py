from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

def auto_login_and_print_body(url_login, username, password, url_target):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url_login)

        # Detecta campo de username/email
        username_input = page.query_selector(
            'input[type="text"], input[type="email"], input[name*="user"], input[name*="email"]'
        )
        if username_input:
            username_input.fill(username)
        else:
            print("Campo de username não encontrado")

        # Detecta campo de senha
        password_input = page.query_selector(
            'input[type="password"], input[name*="pass"], input[name*="senha"]'
        )
        if password_input:
            password_input.fill(password)
        else:
            print("Campo de senha não encontrado")

        # Detecta botão de login
        submit_button = page.query_selector(
            'button[type="submit"], input[type="submit"], button:has-text("Login"), button:has-text("Entrar")'
        )
        if submit_button:
            submit_button.click()
        else:
            print("Botão de login não encontrado")
            return

        # Espera a página pós-login carregar
        page.wait_for_load_state("networkidle")

        # Navega para a página alvo
        page.goto(url_target)
        page.wait_for_load_state("networkidle")

        # Pega o HTML e extrai o body
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        body = soup.body
        print("----- BODY DA PÁGINA ALVO -----")
        print(body.prettify() if body else "Body não encontrado")
        browser.close()

# -------------------------------
# Teste
# -------------------------------

if __name__ == "__main__":
    url_login = "https://the-internet.herokuapp.com/login"
    username = "tomsmith"
    password = "SuperSecretPassword!"
    url_target = "https://the-internet.herokuapp.com/secure"

    auto_login_and_print_body(url_login, username, password, url_target)