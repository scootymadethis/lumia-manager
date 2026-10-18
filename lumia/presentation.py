"""Shared Discord presentation: small caps for channels, readable text for cards."""
import os
import re
from urllib.parse import urlsplit
import discord

SMALL_CAPS=str.maketrans('abcdefghijklmnopqrstuvwxyz','ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘQʀꜱᴛᴜᴠᴡxʏᴢ')
COLORS={'info':0xA7B4CB,'success':0x86D4B4,'warning':0xE5BE7D,'danger':0xE69AA7,'neutral':0x8993A7}
SECTIONS={'server_log':('📡','Registro server'),'mod_log':('🛡️','Moderazione e sicurezza'),'staff_orders':('📋','Ordini e pagamenti')}


def small_caps(text):
    return text.lower().translate(SMALL_CAPS)


def channel_name(text):
    """Use the requested small caps, retaining emoji, separators and numbers."""
    prefix,separator,label=text.partition('・')
    return prefix+separator+small_caps(label.replace(' ','-')) if separator else small_caps(text.replace(' ','-'))


def card(title,text='',*,section='Lumia Development',level='info',fields=(),footer='Lumia Development',timestamp=False,subject=None):
    result=discord.Embed(title=str(title)[:256],description=str(text)[:3000] or None,
                         color=COLORS.get(level,COLORS['info']),
                         timestamp=discord.utils.utcnow() if timestamp else None)
    result.set_author(name=str(section)[:256])
    result.set_footer(text=str(footer)[:256])
    with_avatar(result,subject)
    # Discord rejects embeds above 6000 characters, even if individual fields fit.
    for name,value,inline in fields:
        name=str(name)[:128] or 'Dettaglio'
        remaining=5800-len(result)-len(name)
        if len(result.fields)>=25 or remaining<1:
            break
        result.add_field(name=name,value=str(value)[:min(1024,remaining)] or '—',inline=inline)
    return result


def log_card(key,text,*,title=None,fields=(),level='info'):
    icon,section=SECTIONS.get(key,('✦','Attività'))
    return card(f'{icon}  {title or section}',text,section=f'Lumia Development / {section}',
                level=level,fields=fields,footer='Lumia Manager • Registro riservato allo staff',timestamp=True)


def member_label(number):
    return f'<@{int(number)}>'


def with_avatar(result,subject):
    avatar=getattr(getattr(subject,'display_avatar',None),'url',None)
    if avatar and not result.thumbnail.url:
        result.set_thumbnail(url=str(avatar))
    return result


def dashboard_view(order_id=None):
    origin=os.getenv('LUMIA_PUBLIC_URL','').strip().rstrip('/')
    parsed=urlsplit(origin)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path:
        return None
    url=origin+(f'/orders/{int(order_id)}' if order_id is not None else '/orders')
    view=discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label='Apri il progetto' if order_id else 'Area clienti',
                                   style=discord.ButtonStyle.link,url=url))
    return view


def message_subject(bot,text,fields=()):
    guild=bot.get_guild(bot.cfg['guild_id'])
    # Prefer the subject/customer over the operator when both are present.
    values=sorted(fields,key=lambda f:0 if f[0].lower() in ('membro','cliente','autore','utente') else 1)
    for value in [*(str(f[1]) for f in values),str(text)]:
        match=re.search(r'<@!?(\d+)>',value)
        if match:
            number=int(match.group(1))
            member=guild.get_member(number) if guild and hasattr(guild,'get_member') else None
            return member or (bot.get_user(number) if hasattr(bot,'get_user') else None)
    return None


TEXT_TITLES={
    'welcome':'✦  Benvenuto in Lumia Development',
    'rules':'📜  Il nostro regolamento',
    'services':'🛠️  Diamo forma al tuo server',
    'portfolio':'✧  Progetti e anteprime',
    'faq':'💬  Le risposte, prima di iniziare',
    'suggestions':'💡  Miglioriamo Lumia insieme',
}


def text_card(key,content):
    # Existing editable server_texts.json remains the source of the body copy.
    lines=content.splitlines()
    if key!='faq' and lines and lines[0].startswith('**') and lines[0].endswith('**'):
        content='\n'.join(lines[1:]).lstrip()
    return card(TEXT_TITLES.get(key,'Lumia Development'),content,section='Lumia / Community',
                footer='Lumia Development')
