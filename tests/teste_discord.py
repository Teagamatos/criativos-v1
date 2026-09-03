"""Dispara uma notificação de teste no Discord (não toca ClickUp/Pexels).

Uso:
    # 1. põe no .env:  DISCORD_BOT_TOKEN=...   DISCORD_CHANNEL_ID=1507069228459495436
    # 2. roda:
    python -m tests.teste_discord

Gera um traceback de verdade (divisão por zero dentro de um "pipeline" falso)
e manda pro canal via app.notify.erro_discord — o mesmo caminho que o pipeline
real usa quando quebra.
"""
import asyncio

import httpx

from app import config, notify


async def _diagnostico() -> bool:
    """Checa o token contra GET /users/@me (o jeito canônico de validar) e
    testa os dois esquemas de header. Não imprime o token. Devolve True se
    algum esquema autenticou."""
    bruto = config.DISCORD_BOT_TOKEN
    t = bruto.strip()
    prefixado = t.lower().startswith(("bot ", "bearer "))
    nucleo = t.split(" ", 1)[1].strip() if prefixado else t  # token sem o esquema
    idx_espaco = nucleo.find(" ")
    print("--- diagnóstico ---")
    print(f"valor no .env: {len(bruto)} chars | já vem com 'Bot '/'Bearer ': {prefixado}")
    print(f"token (sem esquema): {len(nucleo)} chars | pontos: {nucleo.count('.')} "
          f"| espaço no meio: {'sim, pos ' + str(idx_espaco) if idx_espaco >= 0 else 'não'} "
          f"| aspas: {chr(34) in nucleo or chr(39) in nucleo}")
    tentativas = {
        "Bot <núcleo>": f"Bot {nucleo}",
        "Bearer <núcleo>": f"Bearer {nucleo}",
        "valor bruto do .env": bruto.strip(),
    }
    ok = False
    async with httpx.AsyncClient(timeout=10) as cli:
        for rotulo, header in tentativas.items():
            r = await cli.get("https://discord.com/api/v10/users/@me",
                              headers={"Authorization": header})
            quem = ""
            if r.status_code == 200:
                ok = True
                j = r.json()
                quem = f" → OK: {j.get('username')} (id {j.get('id')}, bot={j.get('bot')})"
            print(f"  [{rotulo}] → HTTP {r.status_code}{quem}")
    print("-------------------")
    return ok


def _pipeline_falso():
    etapa = "render HTML→PNG"  # noqa: F841 — só pra aparecer no traceback
    dados = {"cargo": "Consultor de Vendas", "task": "TESTE-123"}
    return 1 / 0  # estoura de propósito


async def main() -> None:
    print(f"token setado: {bool(config.DISCORD_BOT_TOKEN)}  canal: {config.DISCORD_CHANNEL_ID or '(vazio)'}")
    if not (config.DISCORD_BOT_TOKEN and config.DISCORD_CHANNEL_ID):
        raise SystemExit("faltou DISCORD_BOT_TOKEN e/ou DISCORD_CHANNEL_ID no .env")

    if not await _diagnostico():
        raise SystemExit(
            "token rejeitado pelo Discord (401 no GET /users/@me). Não adianta enviar.\n"
            "Pega o token atual em: Developer Portal → Applications → [seu app] → Bot →\n"
            "Reset Token → copia inteiro. Cola no .env como DISCORD_BOT_TOKEN= (sem 'Bot ')."
        )

    try:
        _pipeline_falso()
    except Exception as err:
        await notify.erro_discord(
            "🧪 Teste de notificação — task TESTE-123",
            contexto={
                "task": "TESTE-123",
                "cargo": "Consultor de Vendas",
                "etapa": "render HTML→PNG",
                "erro": f"{type(err).__name__}: {err}",
            },
            exc=err,
        )
    print("enviado — confere o canal do Discord (se o Discord recusou, aparece acima no log).")


if __name__ == "__main__":
    asyncio.run(main())
