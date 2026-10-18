import discord
from discord import app_commands
from .presentation import card,with_avatar


def is_management(member,cfg):
    guild = getattr(member,'guild',None)
    return bool(guild and (member.id == guild.owner_id or member.id in cfg.get('owner_ids',[]) or cfg['roles'].get('management',0) in {r.id for r in member.roles}))


def is_support(member,cfg):
    return is_management(member,cfg) or cfg['roles'].get('support',0) in {r.id for r in getattr(member,'roles',[])}


def is_moderator(member,cfg):
    return is_management(member,cfg) or cfg['roles'].get('moderator',0) in {r.id for r in getattr(member,'roles',[])}


def require(interaction,predicate):
    if interaction.guild is None or not predicate(interaction.user):
        raise app_commands.CheckFailure('Non hai accesso a questa funzione.')


async def respond(interaction,text,**kwargs):
    if text and not kwargs.get('embed') and not kwargs.get('embeds') and not kwargs.get('file') and not kwargs.get('files'):
        kwargs['embed']=card('Lumia',str(text),subject=interaction.user)
        text=None
    elif kwargs.get('embed'):
        with_avatar(kwargs['embed'],interaction.user)
    kwargs.setdefault('ephemeral',True)
    kwargs.setdefault('allowed_mentions',discord.AllowedMentions.none())
    if interaction.response.is_done():
        return await interaction.followup.send(text,**kwargs)
    return await interaction.response.send_message(text,**kwargs)


def safe_role(role):
    public = discord.Permissions(
        view_channel=True,send_messages=True,send_messages_in_threads=True,
        embed_links=True,attach_files=True,read_message_history=True,add_reactions=True,
        use_external_emojis=True,use_external_stickers=True,use_application_commands=True,
        connect=True,speak=True,use_voice_activation=True,stream=True,change_nickname=True,
        request_to_speak=True,send_voice_messages=True,send_polls=True)
    return bool(role and not role.managed and role.permissions.value & ~public.value == 0 and not (hasattr(role,'is_default') and role.is_default()))


def embed(title,text):
    return card(title,text)
