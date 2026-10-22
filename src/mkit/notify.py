"""Telegram release notifications. Never fails a release.

Credential: TELEGRAM = {"bot_token": "...", "chat_id": "..."}. On only when
[notify.telegram] is in mkit.toml. Messages are plain HTML: the version and
what happened first, labelled detail underneath, no decoration.
"""
import html
import json
import urllib.parse
import urllib.request

from . import output

API = 'https://api.telegram.org/bot{token}/sendMessage'


def esc(value):
    return html.escape(str(value), quote=False)


def enabled(ctx):
    return ctx.project.has('notify.telegram') and ctx.secrets.has('TELEGRAM')


def message(ctx, subject, headline, fields=()):
    lines = [f'<b>{esc(ctx.project.name)} {esc(subject)}</b>', headline]
    detail = [f'{label}: {esc(value)}' for label, value in fields if value]
    if detail:
        lines += [''] + detail
    return '\n'.join(lines)


def send(ctx, text):
    """True if delivered. Problems only warn: the success path runs when a build
    is already live, and a failure path must not swap its real error for a
    chat-delivery one."""
    if not enabled(ctx):
        return False
    creds = ctx.secrets.json('TELEGRAM')
    fields = {'chat_id': creds['chat_id'], 'text': text, 'parse_mode': 'HTML',
              'link_preview_options': json.dumps({'is_disabled': True})}
    request = urllib.request.Request(API.format(token=creds['bot_token']),
                                     data=urllib.parse.urlencode(fields).encode('utf-8'))
    try:
        urllib.request.urlopen(request, timeout=30)
        return True
    except Exception as e:
        output.out.warn(f'Telegram notification failed: {type(e).__name__}')
        return False
