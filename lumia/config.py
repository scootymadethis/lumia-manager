import copy
import json
from pathlib import Path

ROLE_KEYS = ('management','support','moderator','developer','member','unverified','customer','fivem','minecraft','web','news','release')
# member_counter is retained only to identify/detach counters in older installations.
CHANNEL_KEYS = ('welcome','rules','verification','announcements','services','portfolio','faq','role_panel','ticket_panel','transcripts','mod_log','server_log','staff_orders','events','suggestions','general','member_counter')


def snowflake(value):
    if isinstance(value, bool):
        raise ValueError('Gli ID Discord devono essere numeri, non true/false.')
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError('ID Discord non valido.') from None
    if number < 0 or str(number) != str(value):
        raise ValueError('ID Discord non valido.')
    return number


def validate_config(raw):
    cfg = copy.deepcopy(raw)
    cfg['guild_id'] = snowflake(cfg.get('guild_id',0))
    if not cfg['guild_id']:
        raise ValueError('Inserisci guild_id con l’ID del tuo server Discord in config.json.')
    if not isinstance(cfg.get('owner_ids',[]),list):
        raise ValueError('owner_ids deve essere un elenco di ID.')
    cfg['owner_ids'] = [snowflake(n) for n in cfg.get('owner_ids',[])]
    for name, keys in (('roles',ROLE_KEYS),('channels',CHANNEL_KEYS),('categories',('start','info','community','tickets','private_tickets','staff'))):
        if not isinstance(cfg.get(name,{}),dict):
            raise ValueError(f'{name} deve essere un oggetto JSON.')
        cfg[name] = {key:snowflake(cfg.get(name,{}).get(key,0)) for key in keys}
    roleids=[v for v in cfg['roles'].values() if v]
    if len(roleids)!=len(set(roleids)):
        raise ValueError('Ogni ruolo configurato deve avere un ID distinto: staff e ruoli pubblici non possono coincidere.')
    cfg.setdefault('timezone','Europe/Rome')
    cfg.setdefault('retention_days',90)
    if type(cfg['retention_days']) is not int or not 7 <= cfg['retention_days'] <= 3650:
        raise ValueError('retention_days deve essere un intero tra 7 e 3650.')
    cfg['automod'] = {'enabled':False,'spam_count':7,'spam_seconds':8,'blocked_domains':[], 'ignore_channels':[], **cfg.get('automod',{})}
    cfg['security'] = {'mode':'observe','join_limit':10,'join_window':60,'young_days':7,'audit_limit':4,'audit_window':60,'whitelist_users':[], **cfg.get('security',{})}
    if type(cfg['automod']['enabled']) is not bool:
        raise ValueError('automod.enabled deve essere true o false, senza virgolette.')
    if not isinstance(cfg['automod']['blocked_domains'],list) or any(not isinstance(v,str) for v in cfg['automod']['blocked_domains']):
        raise ValueError('blocked_domains deve essere un elenco di domini.')
    for group,key in (('automod','ignore_channels'),('security','whitelist_users')):
        if not isinstance(cfg[group][key],list):
            raise ValueError(f'{group}.{key} deve essere un elenco di ID.')
        cfg[group][key]=[snowflake(v) for v in cfg[group][key]]
    if cfg['security']['mode'] not in ('observe','enforce'):
        raise ValueError('security.mode deve essere observe o enforce.')
    for section, keys in (('automod',('spam_count','spam_seconds')),('security',('join_limit','join_window','young_days','audit_limit','audit_window'))):
        for key in keys:
            if type(cfg[section][key]) is not int or cfg[section][key] <= 0:
                raise ValueError(f'{section}.{key} deve essere un intero positivo.')
    return cfg


def load_config(path):
    return validate_config(json.loads(Path(path).read_text(encoding='utf-8-sig')))


def save_config(path,cfg):
    target = Path(path)
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(target)
