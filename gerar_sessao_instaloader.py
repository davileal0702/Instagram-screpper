import sys
import os
import re
import time
from glob import glob
from os.path import expanduser
from platform import system
from sqlite3 import OperationalError, connect
from pathlib import Path
from getpass import getpass

import instaloader
from instaloader import exceptions as iex


def project_root() -> Path:
    return Path(__file__).resolve().parent


def sessions_dir() -> Path:
    custom = (os.environ.get("INSTA_SESSIONS_DIR", "") or "").strip().strip('"')
    if custom:
        p = Path(custom)
    else:
        # Padrão compartilhado com o backend CGI no Windows/XAMPP
        p = Path(r"C:\xampp\insta_sessions") if os.name == "nt" else (project_root() / "insta_sessions")
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_session_path(username: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", username)
    return sessions_dir() / f".instaloader_session_{safe}"


def list_local_sessions():
    items = []
    for p in sorted(sessions_dir().glob(".instaloader_session_*"), key=lambda x: x.name.lower()):
        user = p.name[len(".instaloader_session_"):]
        if user:
            items.append(user)
    return items


def find_firefox_cookiefiles():
    pattern = {
        "Windows": "~/AppData/Roaming/Mozilla/Firefox/Profiles/*/cookies.sqlite",
        "Darwin": "~/Library/Application Support/Firefox/Profiles/*/cookies.sqlite",
    }.get(system(), "~/.mozilla/firefox/*/cookies.sqlite")

    files = glob(expanduser(pattern))
    # Tenta priorizar o arquivo mais recente
    files = sorted(files, key=lambda p: Path(p).stat().st_mtime if Path(p).exists() else 0, reverse=True)
    return files


def import_session_from_firefox():
    """
    Importa cookies do Firefox (Instagram) e salva sessão do Instaloader.
    Baseado no exemplo oficial 615_import_firefox_session.py (adaptado).
    """
    print("\n=== Importar sessão do Firefox (recomendado) ===")
    print("Pré-requisito: esteja logado no Instagram no Firefox (na conta desejada).")

    cookiefiles = find_firefox_cookiefiles()
    if not cookiefiles:
        print("❌ Nenhum cookies.sqlite do Firefox foi encontrado.")
        print("Instale/abra o Firefox e faça login no Instagram nele, ou use o login por senha (opção 2).")
        return 11

    print("\nPerfis do Firefox encontrados:")
    for i, cf in enumerate(cookiefiles, start=1):
        print(f"{i:02d}. {cf}")

    raw = input("Escolha o número do cookies.sqlite (ENTER = 1): ").strip()
    if not raw:
        idx = 1
    elif raw.isdigit():
        idx = int(raw)
    else:
        print("❌ Entrada inválida.")
        return 12

    if idx < 1 or idx > len(cookiefiles):
        print("❌ Índice fora da faixa.")
        return 13

    cookiefile = cookiefiles[idx - 1]
    print(f"\n→ Usando cookies do Firefox: {cookiefile}")

    try:
        conn = connect(f"file:{cookiefile}?immutable=1", uri=True)
        try:
            try:
                cookie_data = conn.execute(
                    "SELECT name, value FROM moz_cookies WHERE baseDomain='instagram.com'"
                ).fetchall()
            except OperationalError:
                cookie_data = conn.execute(
                    "SELECT name, value FROM moz_cookies WHERE host LIKE '%instagram.com'"
                ).fetchall()
        finally:
            conn.close()

        if not cookie_data:
            print("❌ Não encontrei cookies do Instagram nesse perfil do Firefox.")
            print("Confirme se você está logado no Instagram nesse perfil do navegador.")
            return 14

        L = instaloader.Instaloader(quiet=True, max_connection_attempts=1)
        L.context._session.cookies.update(cookie_data)

        username = L.test_login()
        if not username:
            print("❌ Os cookies foram lidos, mas não há sessão logada válida no Instagram.")
            print("Abra o Instagram no Firefox, confirme que está logado, e tente novamente.")
            return 15

        L.context.username = username
        session_file = default_session_path(username)
        session_file.parent.mkdir(parents=True, exist_ok=True)
        L.save_session_to_file(str(session_file))

        print(f"✅ Sessão importada do Firefox para @{username}")
        print(f"✅ Sessão salva em: {session_file}")
        print("\nPróximo passo no site:")
        print("1) Abra http://localhost/index.html")
        print("2) Clique em 'Atualizar lista'")
        print(f"3) Selecione @{username}")

        return 0

    except (OperationalError, iex.ConnectionException) as e:
        print(f"❌ Falha ao importar cookies do Firefox: {type(e).__name__} - {e}")
        return 16
    except Exception as e:
        print(f"❌ Erro inesperado na importação do Firefox: {type(e).__name__} - {e}")
        return 17


def looks_like_temp_block(msg: str) -> bool:
    s = (msg or "").lower()
    return any(x in s for x in (
        "please wait a few minutes",
        "please wait a few minutes before you try again",
        "429",
        "too many requests",
        "401 unauthorized",
        "feedback_required",
    ))


def checkpoint_url_from_message(msg: str) -> str:
    m = re.search(r"https?://[^\s'\"<>]+", msg or "")
    return m.group(0).rstrip(").,;") if m else ""


def login_por_senha():
    """
    Mantém o fluxo antigo como fallback opcional.
    """
    print("\n=== Cadastrar por login/senha (fallback) ===")
    username = input("Usuário Instagram (sem @): ").strip().lstrip("@")
    password = getpass("Senha: ")

    if not username:
        print("❌ Usuário obrigatório.")
        return 1

    session_file = default_session_path(username)
    L = instaloader.Instaloader(quiet=True)

    while True:
        try:
            print(f"\n→ Tentando login em @{username}...")
            L.login(username, password)
            break

        except iex.TwoFactorAuthRequiredException:
            code = input("Digite o código 2FA (6 dígitos): ").strip()
            try:
                L.two_factor_login(code)
                break
            except Exception as e:
                print(f"❌ Falha no two_factor_login: {type(e).__name__} - {e}")
                if looks_like_temp_block(str(e)):
                    print("⚠️ Instagram bloqueou temporariamente. Aguarde e tente novamente.")
                return 2

        except (iex.LoginException, iex.ConnectionException) as e:
            msg = str(e)

            if "checkpoint required" in msg.lower():
                url = checkpoint_url_from_message(msg)
                print("\n⚠️ CHECKPOINT REQUIRED")
                if url:
                    print("Abra no navegador e conclua a validação:")
                    print(url)
                else:
                    print(msg)
                input("\nDepois de concluir, pressione ENTER para tentar novamente (ou Ctrl+C para sair)... ")
                time.sleep(2)
                continue

            if looks_like_temp_block(msg):
                print(f"❌ Bloqueio temporário do Instagram: {msg}")
                print("Aguarde alguns minutos (às vezes horas) e tente de novo.")
                return 3

            # Caso clássico que você pegou: fail status, message ""
            print(f"❌ Erro de login: {type(e).__name__} - {e}")
            print("💡 Dica: esse erro genérico costuma acontecer antes de chegar no 2FA.")
            print("💡 Use a opção 1 (Importar sessão do Firefox), que é mais confiável.")
            return 4

        except KeyboardInterrupt:
            print("\n⛔ Cancelado pelo usuário.")
            return 130

        except Exception as e:
            print(f"❌ Erro inesperado: {type(e).__name__} - {e}")
            return 5

    session_file.parent.mkdir(parents=True, exist_ok=True)
    L.save_session_to_file(str(session_file))
    print(f"✅ Sessão salva em: {session_file}")
    print(f"✅ Usuário detectável no site (session_user): {username}")

    print("\nPróximo passo no site:")
    print("1) Abra http://localhost/index.html")
    print("2) Clique em 'Atualizar lista'")
    print(f"3) Selecione @{username}")

    ans = input("\nValidar agora com test_login()? (s/N): ").strip().lower()
    if ans in {"s", "sim", "y", "yes"}:
        try:
            who = L.test_login()
            print(f"✅ test_login(): {who}")
        except Exception as e:
            print("⚠️ Sessão salva, mas test_login() falhou (possível bloqueio temporário).")
            print(f"Detalhe: {type(e).__name__} - {e}")

    return 0


def main():
    print("=== Gerar Sessão Instaloader (POC local) ===")
    print(f"📁 Pasta padrão de sessões: {sessions_dir()}")

    while True:
        print("\nEscolha o método de cadastro:")
        print("1) Importar sessão do Firefox (RECOMENDADO / mais confiável)")
        print("2) Login por senha (fallback)")
        print("3) Sair")

        opt = input("> ").strip() or "1"

        if opt == "1":
            code = import_session_from_firefox()
            if code not in (0, None):
                print(f"(retorno {code})")
            # após sucesso ou erro, volta ao menu para permitir outra tentativa
        elif opt == "2":
            code = login_por_senha()
            if code not in (0, None):
                print(f"(retorno {code})")
        elif opt == "3":
            print("Saindo.")
            sys.exit(0)
        else:
            print("Opção inválida.")


if __name__ == "__main__":
    main()