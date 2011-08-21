from google.appengine.ext import db

# in how many groups we'll split all characters
# 60 is we check once per minute and each character is checked every hour
TICKS_BETWEEN_CHECKS = 60

class Tick(db.Model):
    """Each tick is a parent to all accounts which have to be checked at once."""
    pos = db.IntegerProperty() # Tick number
    num = db.IntegerProperty() # Number of accounts bound to this tick
    accts = db.ListProperty(db.Key)

def register_key(key):
    usedTicks = Tick.all(keys_only=True).count(TICKS_BETWEEN_CHECKS)
    if usedTicks < TICKS_BETWEEN_CHECKS: # got some empty ticks
        tick = Tick(pos=usedTicks, num=0)
    else:
        tick = Tick.all().ancestor(tracker).order('num').get()

    tick.accts.append(key)
    tick.num += 1
    tick.put()
