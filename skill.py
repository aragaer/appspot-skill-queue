import logging
from eveapi.eveapi import EVEAPIConnection
from google.appengine.ext import db

api = EVEAPIConnection()

class Skill(db.Model):
    """Maps skills to their names, nothing fancy"""
    name = db.StringProperty(required=True)

def skill_key(ID):
    return db.Key.from_path('Skill', ID)

def skill_id(skill):
    return int(skill.key().name())

def get_names(IDs):
    res = {}
    IDs = map(int, IDs) # make sure IDs are integers, not strings
    logging.debug("Looking up skill names for skills %s" % IDs)
    for skill in Skill.get(map(skill_key, IDs)):
        if skill:
            res[skill.key().id()] = skill.name
    logging.debug("Found the following so far: %s" % IDs)

    IDs_to_request = ','.join([str(ID) for ID in IDs if not ID in res])

    if IDs_to_request:
        for s in api.eve.CharacterName(ids=IDs_to_request).characters:
            ID = s.characterID
            name = s.name
            skill = Skill(key=skill_key(ID), name=name)
            skill.put()
            res[ID] = name
    return res

