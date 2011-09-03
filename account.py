from eveapi.eveapi import EVEAPIConnection
import datetime
import skill
import tick
import logging
from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.runtime.apiproxy_errors import CapabilityDisabledError, DeadlineExceededError

api = EVEAPIConnection()

class Account(db.Model):
    """Each queue is bound to account. Thus we use accounts for checking."""
    ID = db.IntegerProperty(required=True)
    owner = db.UserProperty(auto_current_user_add=True)
    vCode = db.StringProperty()
    queueEnd = db.DateTimeProperty()
    training = db.ReferenceProperty()
    chars = db.ListProperty(db.Key)
    def auth(self):
        return api.auth(keyID=self.ID, vCode=self.vCode)

    def add_character(self, charID, charName=None):
        character = Character.get(char_key(charID))
        if character: # Already registered
            raise Exception("Character %s is already registered" % character.name)
        character = Character(acct=self, key=char_key(charID), ID=charID)
        if charName:
            character.name = charName
        else: # some artificial way of adding characters
            for r in api.eve.CharacterName(ids=charID).characters: # single row here
                character.name = r.name
        character.put()
        self.chars.append(char_key(charID))
        self.put()

        return character

    def check_queue(self):
        """Check the state of skill queue for this account."""
        training = self.training
        if training:        # check the one currently training first
            training.refreshQueue()
            if not self.training:                       # he is no longer training
                for char in Character.get(self.chars):  # check the rest
                    if char.ID != training.ID:
                        char.refreshQueue()
                        if self.training:               # this one is training
                            break
        else:               # check everyone
            for char in Character.get(self.chars):
                char.refreshQueue()
                if self.training:
                    break

        return (self.training, self.queueEnd)

def acct_key(ID):
    return db.Key.from_path('Account', ID)

def try_add_account(keyID, vCode):
    account = Account.get(acct_key(keyID))
    if account:
        if account.owner != users.get_current_user():
            raise Exception("Account created by another user")
    else:
        account = Account(key=acct_key(keyID), ID=keyID, vCode=vCode)
        account.put()
        tick.register_key(account.key())
    return account

class Character(db.Model):
    acct = db.ReferenceProperty(required=True)
    name = db.StringProperty()
    ID = db.IntegerProperty(required=True)
    cachedUntil = db.DateTimeProperty()
    queue = db.StringListProperty()

    def refreshQueue(self):
        """Don't care about results. Just refresh db entries."""
        if not self.cachedUntil or self.cachedUntil < datetime.datetime.utcnow():
            try:
                self.getQueueOnline()
            except CapabilityDisabledError:
                pass
            except Exception, exc:
                logging.error("Error refreshing queue for %s (%d): %s" % (self.name, self.ID, exc))
        else:
            logging.debug("Not refreshing queue for character %s since it is still cached" % self.name)

    def getQueue(self):
        if self.cachedUntil and self.cachedUntil > datetime.datetime.utcnow():
            (queue, skills) = self.getQueueCached()
        else:
            (queue, skills) = self.getQueueOnline()

        for ID, name in skill.get_names(skills.keys()).items():
            for rec in skills[ID]:
                rec['name'] = name

        return queue

    def getQueueOnline(self):
        res = []
        skills = {}
        queue = self.acct.auth().char.SkillQueue(characterID=self.ID)
        self.cachedUntil = datetime.datetime.fromtimestamp(queue._meta.cachedUntil)
        self.queue = []
        for s in queue.skillqueue:
            ID = s.typeID
            res.append({
                'id':   ID,
                'level':s.level,
                'end':  datetime.datetime.fromtimestamp(s.endTime),
            })
            last = res[-1]
            self.queue.append("%s" % last)
            if ID in skills:
                skills[ID].append(last)
            else:
                skills[ID] = [last]

        if res:
            self.acct.queueEnd = last['end']
            self.acct.training = self
            self.acct.put()
        elif self.acct.training.ID == self.ID:
            self.acct.training = None
            self.acct.training = datetime.datetime.utcnow()
            self.acct.put()

        self.put()
        return (res, skills)

    def getQueueCached(self):
        skills = {}
        queue = []
        for rec in map(eval, self.queue):
            queue.append(rec)
            ID = rec['id']
            if ID in skills:
                skills[ID].append(rec)
            else:
                skills[ID] = [rec]

        return (queue, skills)

def char_key(ID):
    return db.Key.from_path('Character', ID)

def get_character_by_id(ID):
    return Character.get(char_key(ID))

def get_character_by_id_secure(ID):
    character = Character.get(char_key(ID))
    if not character:
        raise Exception("No such character")
    if character.acct.owner != users.get_current_user():
        raise Exception("Wrong owner")
    return character

def get_my_characters():
    chars = []
    for account in Account.all().filter("owner = ", users.get_current_user()):
        chars.extend(Character.all().filter("acct = ", account))
    return chars
