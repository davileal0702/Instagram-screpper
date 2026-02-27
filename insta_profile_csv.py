#!C:/Users/davil/Documentos/GitHub/Scrapping/Instagram-screpper/.venv/Scripts/python.exe
# -*- coding: utf-8 -*-

import io
import sys
import csv
import json
import os
import html
from pathlib import Path
from urllib.parse import parse_qs

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# -------------------------------
# Configuração local (POC)
# -------------------------------
def project_root() -> Path:
    here = Path(__file__).resolve().parent
    return here.parent if here.name.lower() == "cgi-bin" else here


def sessions_dir() -> Path:
    custom = (os.environ.get("INSTA_SESSIONS_DIR", "") or "").strip().strip('"')
    if custom:
        p = Path(custom)
    else:
        # Padrão compartilhado com o script de cadastro no Windows/XAMPP
        p = Path(r"C:\xampp\insta_sessions") if os.name == "nt" else (project_root() / "insta_sessions")
    p.mkdir(parents=True, exist_ok=True)
    return p


def sanitize_username(username: str) -> str:
    username = (username or "").strip().lstrip("@")
    return "".join(c for c in username if c.isalnum() or c in "._-")


def session_path_for_user(username: str) -> Path:
    safe = sanitize_username(username)
    return sessions_dir() / f".instaloader_session_{safe}"


def list_saved_sessions():
    sd = sessions_dir()
    items = []
    for p in sorted(sd.glob(".instaloader_session_*"), key=lambda x: x.name.lower()):
        user = p.name[len(".instaloader_session_"):]
        if not user:
            continue

        try:
            mtime_ts = p.stat().st_mtime
        except Exception:
            mtime_ts = 0

        mtime = ""
        if mtime_ts:
            try:
                import datetime as _dt
                mtime = _dt.datetime.fromtimestamp(mtime_ts).strftime("%d/%m/%Y %H:%M")
            except Exception:
                mtime = ""

        items.append({
            "user": user,
            "mtime": mtime,
            "_mtime_ts": mtime_ts,
        })

    # Mais recentes primeiro (por timestamp real)
    items.sort(key=lambda x: x.get("_mtime_ts", 0), reverse=True)

    for item in items:
        item.pop("_mtime_ts", None)

    return items


def delete_saved_session(username: str):
    user = sanitize_username(username)
    if not user:
        return {"ok": False, "error": "session_user inválido."}

    p = session_path_for_user(user)
    if not p.exists():
        return {"ok": False, "error": f"Sessão não encontrada para @{user}.", "user": user}

    try:
        p.unlink()
        return {"ok": True, "user": user}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "user": user}


# -------------------------------
# Respostas CGI
# -------------------------------
def send_html(message: str, status: str = "200 OK", title: str = "Resultado"):
    print(f"Status: {status}")
    print("Content-Type: text/html; charset=utf-8")
    print("Cache-Control: no-store")
    print()
    print(
        f"<!DOCTYPE html><html lang='pt-BR'><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"</head><body style='font-family:Arial,sans-serif;padding:20px;background:#f8fafc'>"
        f"<div style='max-width:900px;margin:0 auto;background:#fff;padding:18px;border-radius:12px;box-shadow:0 6px 20px rgba(0,0,0,.08)'>"
        f"<h2 style='margin-top:0'>{html.escape(title)}</h2>"
        f"<div style='white-space:pre-wrap;background:#f8fafc;padding:12px;border:1px solid #e5e7eb;border-radius:8px'>{html.escape(message)}</div>"
        f"<p><a href='/index.html'>Voltar</a></p></div></body></html>"
    )


def send_json(obj, status: str = "200 OK"):
    print(f"Status: {status}")
    print("Content-Type: application/json; charset=utf-8")
    print("Cache-Control: no-store")
    print()
    print(json.dumps(obj, ensure_ascii=False))


# -------------------------------
# Request parsing
# -------------------------------
def parse_request():
    method = os.environ.get("REQUEST_METHOD", "GET").upper()
    qs = os.environ.get("QUERY_STRING", "")
    query_params = parse_qs(qs, keep_blank_values=True)

    if method == "GET":
        action = (query_params.get("action", [""])[0] or "").strip().lower()
        if action == "list_sessions":
            return {"_method": "GET", "_action": "list_sessions"}, None
        return {"_method": "GET", "_action": "none"}, None

    if method != "POST":
        return None, "Método HTTP não suportado. Use GET (list_sessions) ou POST."

    try:
        n = int(os.environ.get("CONTENT_LENGTH", "0"))
    except ValueError:
        n = 0
    body = sys.stdin.read(n) if n > 0 else ""
    params = parse_qs(body, keep_blank_values=True)

    def g(k, d=""):
        return (params.get(k, [d])[0] or "").strip()

    action = g("action", "").lower()

    # Endpoint POST para excluir sessão salva
    if action == "delete_session":
        return {
            "_method": "POST",
            "_action": "delete_session",
            "session_user": g("session_user").lstrip("@"),
        }, None

    # Formulário de pesquisa
    auth_mode = g("auth_mode", "session").lower()
    if auth_mode not in {"session", "anonymous"}:
        auth_mode = "session"

    try:
        max_posts = int(g("max_posts", "10"))
    except ValueError:
        max_posts = 10

    data = {
        "_method": "POST",
        "_action": "search",
        "auth_mode": auth_mode,
        "session_user": g("session_user").lstrip("@"),
        "target_user": g("target_user").lstrip("@"),
        "max_posts": max(1, min(max_posts, 50)),
    }

    if not data["target_user"]:
        return None, "Informe o perfil alvo."
    return data, None


# -------------------------------
# Instaloader helpers
# -------------------------------
def import_instaloader():
    try:
        import instaloader
        from instaloader import Profile
        return instaloader, Profile
    except Exception as e:
        raise RuntimeError(f"Falha ao importar instaloader (Python do CGI errado?). {type(e).__name__}: {e}")


def build_loader(instaloader_mod):
    return instaloader_mod.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
    )


def txt(e):
    return f"{type(e).__name__} - {e}"


def is_temp_block(s):
    s = (s or "").lower()
    return any(x in s for x in [
        "please wait a few minutes",
        "401 unauthorized",
        "429",
        "too many requests",
        "feedback_required",
    ])


def try_load_session(L, session_user):
    session_user = sanitize_username(session_user)
    if not session_user:
        return {"ok": False, "status": "SESSION_INPUT_MISSING", "detail": "Selecione um perfil cadastrado."}

    p = session_path_for_user(session_user)
    if not p.exists():
        return {"ok": False, "status": "SESSION_FILE_NOT_FOUND", "detail": str(p), "session_file": str(p)}

    try:
        L.load_session_from_file(session_user, str(p))
        return {
            "ok": True,
            "status": "SESSION_LOADED",
            "detail": f"Sessão carregada para @{session_user}",
            "session_file": str(p),
        }
    except Exception as e:
        return {
            "ok": False,
            "status": "SESSION_LOAD_ERROR",
            "detail": txt(e),
            "session_file": str(p),
        }


def choose_auth(parsed, L):
    req = parsed["auth_mode"]
    meta = {
        "execution_mode_requested": req,
        "auth_mode_used": "",
        "auth_status": "",
        "auth_detail": "",
        "session_user_used": parsed.get("session_user", ""),
        "session_file_used": "",
    }

    if req == "anonymous":
        meta.update(
            auth_mode_used="anonymous",
            auth_status="ANONYMOUS_OK",
            auth_detail="Modo anônimo selecionado."
        )
        return meta

    s = try_load_session(L, parsed.get("session_user", ""))
    meta.update(
        auth_mode_used="session",
        auth_status=s["status"],
        auth_detail=s["detail"],
        session_user_used=parsed.get("session_user", ""),
        session_file_used=s.get("session_file", ""),
    )
    return meta


# -------------------------------
# Coleta e CSV
# -------------------------------
def collect(Profile, L, target_user, max_posts, auth_meta):
    profile = Profile.from_username(L.context, target_user)
    rows = []

    for i, post in enumerate(profile.get_posts(), start=1):
        if i > max_posts:
            break

        caption = (getattr(post, "caption", "") or "").replace("\n", " ").replace("\r", " ").strip()

        rows.append({
            "execution_mode_requested": auth_meta.get("execution_mode_requested", ""),
            "auth_mode_used": auth_meta.get("auth_mode_used", ""),
            "auth_status": auth_meta.get("auth_status", ""),
            "auth_detail": auth_meta.get("auth_detail", ""),
            "session_user_used": auth_meta.get("session_user_used", ""),
            "profile_username": profile.username,
            "profile_full_name": profile.full_name or "",
            "profile_followers": getattr(profile, "followers", None),
            "profile_followees": getattr(profile, "followees", None),
            "profile_mediacount": getattr(profile, "mediacount", None),
            "profile_is_private": getattr(profile, "is_private", None),
            "profile_is_verified": getattr(profile, "is_verified", None),
            "profile_is_business_account": getattr(profile, "is_business_account", None),
            "post_index": i,
            "shortcode": getattr(post, "shortcode", ""),
            "date_utc": post.date_utc.isoformat() if getattr(post, "date_utc", None) else "",
            "likes": getattr(post, "likes", None),
            "comments": getattr(post, "comments", None),
            "is_video": getattr(post, "is_video", None),
            "caption": caption[:500],
            "owner_username": getattr(post, "owner_username", ""),
            "url": f"https://www.instagram.com/p/{post.shortcode}/" if getattr(post, "shortcode", None) else "",
        })

    return profile, rows


def send_csv(filename, rows):
    headers = [
        "execution_mode_requested", "auth_mode_used", "auth_status", "auth_detail", "session_user_used",
        "profile_username", "profile_full_name", "profile_followers", "profile_followees",
        "profile_mediacount", "profile_is_private", "profile_is_verified", "profile_is_business_account",
        "post_index", "shortcode", "date_utc", "likes", "comments", "is_video", "caption", "owner_username", "url"
    ]

    s = io.StringIO()
    s.write("\ufeff")
    w = csv.DictWriter(s, fieldnames=headers)
    w.writeheader()
    for r in rows:
        w.writerow(r)

    data = s.getvalue().encode("utf-8")

    print("Status: 200 OK")
    print("Content-Type: text/csv; charset=utf-8")
    print(f'Content-Disposition: attachment; filename="{filename}"')
    print("Cache-Control: no-store")
    print()
    sys.stdout.flush()

    if hasattr(sys.stdout, "buffer"):
        sys.stdout.buffer.write(data)
    else:
        sys.stdout.write(s.getvalue())


# -------------------------------
# Main
# -------------------------------
def main():
    try:
        parsed, err = parse_request()
        if err:
            return send_html(err, "400 Bad Request", "Requisição inválida")

        # GET /cgi-bin/insta_profile_csv.py?action=list_sessions
        if parsed.get("_method") == "GET" and parsed.get("_action") == "list_sessions":
            return send_json({
                "ok": True,
                "sessions": list_saved_sessions(),
                "sessions_dir": str(sessions_dir()),
            })

        # POST delete_session
        if parsed.get("_method") == "POST" and parsed.get("_action") == "delete_session":
            result = delete_saved_session(parsed.get("session_user", ""))
            status = "200 OK" if result.get("ok") else "400 Bad Request"
            return send_json(result, status=status)

        # GET normal sem action
        if parsed.get("_method") == "GET":
            return send_html("Use a interface em /index.html e envie o formulário.", title="POC Instaloader")

        # Pesquisa (POST)
        instaloader_mod, Profile = import_instaloader()
        L = build_loader(instaloader_mod)
        auth_meta = choose_auth(parsed, L)

        if parsed["auth_mode"] == "session" and auth_meta.get("auth_status") != "SESSION_LOADED":
            return send_html(
                "Falha ao carregar sessão salva.\n"
                f"Modo pedido: {parsed['auth_mode']}\n"
                f"Status: {auth_meta.get('auth_status')}\n"
                f"Detalhe: {auth_meta.get('auth_detail')}\n\n"
                "Para cadastrar/renovar um perfil, use o script gerar_sessao_instaloader.py (terminal).",
                "401 Unauthorized",
                "Falha de autenticação"
            )

        try:
            profile, rows = collect(Profile, L, parsed["target_user"], parsed["max_posts"], auth_meta)
        except Exception as e:
            msg = txt(e)

            if is_temp_block(msg):
                return send_html(
                    "Instagram bloqueou temporariamente a coleta desta requisição.\n\n"
                    f"Perfil alvo: @{parsed.get('target_user')}\n"
                    f"Auth mode usado: {auth_meta.get('auth_mode_used')}\n"
                    f"Status de auth: {auth_meta.get('auth_status')}\n"
                    f"Detalhe técnico: {msg}\n\n"
                    "O que fazer agora:\n"
                    "1) Aguarde alguns minutos antes de tentar novamente.\n"
                    "2) Evite várias tentativas seguidas.\n"
                    "3) Se possível, use uma sessão salva em vez de modo anônimo.\n"
                    "4) Se persistir, renove a sessão com gerar_sessao_instaloader.py.",
                    "429 Too Many Requests",
                    "Bloqueio temporário do Instagram"
                )

            return send_html(
                "Falha na coleta de dados do perfil/posts.\n\n"
                f"Perfil alvo: @{parsed.get('target_user')}\n"
                f"Auth mode usado: {auth_meta.get('auth_mode_used')}\n"
                f"Status de auth: {auth_meta.get('auth_status')}\n"
                f"Erro: {msg}",
                "500 Internal Server Error",
                "Erro na coleta"
            )

        if not rows:
            return send_html(
                f"Perfil @{profile.username} encontrado, mas não houve posts retornados.\n\n"
                f"Auth mode usado: {auth_meta.get('auth_mode_used')}\n"
                f"Status: {auth_meta.get('auth_status')}\n"
                f"Detalhe: {auth_meta.get('auth_detail')}",
                title="Sem posts para exportar"
            )

        safe = "".join(c for c in parsed["target_user"] if c.isalnum() or c in ("_", "-")).strip() or "perfil"
        send_csv(f"instagram_{safe}.csv", rows)

    except Exception as e:
        msg = f"{type(e).__name__} - {e}"
        if is_temp_block(msg):
            return send_html(
                "Instagram respondeu com bloqueio temporário nesta requisição.\n\n"
                f"Detalhe técnico: {msg}\n\n"
                "Aguarde alguns minutos antes de tentar novamente e evite múltiplas tentativas seguidas.",
                "429 Too Many Requests",
                "Bloqueio temporário do Instagram"
            )
        send_html(f"Erro inesperado: {msg}", "500 Internal Server Error", "Erro interno")


if __name__ == "__main__":
    main()