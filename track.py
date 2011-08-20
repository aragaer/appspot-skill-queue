import cgi, datetime, urllib, wsgiref.handlers, os

from google.appengine.ext import db, webapp
from google.appengine.api import users, mail
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api.urlfetch import fetch
from xml.dom.minidom import parseString

from google.appengine.ext.webapp import template

EVE_URI = "https://api.eveonline.com"
EVE_TEST_URI = "https://apitest.eveonline.com"

#EVE_URI = EVE_TEST_URI

API_PATHS = {
    'CharName': '/eve/CharacterName.xml.aspx',
    'SkillName': '/eve/CharacterName.xml.aspx',
    'SkillQueue': '/char/SkillQueue.xml.aspx',
}

class Skill(db.Model):
    name = db.StringProperty(required=True)
    @staticmethod
    def getNames(ids):
        res = {}
        for skill in Skill.get_by_key_name(ids):
            if skill:
                res[skill.key().name()] = skill.name

        if isinstance(ids, list):
            ids_to_request = [id for id in ids if not id in res]
        elif not ids in res: # just one id and we don't have it yet
            ids_to_request = [ids]

        if ids_to_request:
            data = fetch(EVE_URI+API_PATHS['SkillName'], method='POST', payload='ids=%s' % ','.join(ids_to_request))
            doc = parseString(data.content)
            for row in doc.getElementsByTagName('row'):
                id = row.getAttribute('characterID')
                name = row.getAttribute('name')
                skill = Skill.get_or_insert(key_name=id, name=name)
                res[id] = name
        return res

class Account(db.Model):
    owner = db.UserProperty(auto_current_user_add=True)

class Character(db.Model):
    acct = db.ReferenceProperty(Account)
    apiKey = db.StringProperty()
    name = db.StringProperty()
    owner = db.UserProperty(auto_current_user_add=True)
    ID = db.IntegerProperty()
    queueEnd = db.DateTimeProperty()
    cachedUntil = db.DateTimeProperty()
    queue = db.StringListProperty()

    @staticmethod
    def getByID(id):
        character = Character.get_by_key_name(id)
        if not character:
            raise Exception("No such character")
        if character.owner != users.get_current_user():
            raise Exception("Wrong owner")
        return character

    def getQueue(self):
        if self.cachedUntil and self.cachedUntil > datetime.datetime.utcnow():
            return self.getQueueCached()
        else:
            return self.getQueueOnline()

    def getQueueOnline(self):
        args = urllib.urlencode({
            'userID': self.acct.key().name(),
            'apiKey': self.apiKey,
            'characterID': self.ID
        })
        data = fetch(EVE_URI+API_PATHS['SkillQueue'], method='POST', payload=args)
        doc = parseString(data.content)
        queue = []
        skills = {}
        self.cachedUntil = parseEveDateTime(doc.getElementsByTagName('cachedUntil')[0].firstChild.data)
        self.queue = []
        for row in doc.getElementsByTagName('row'):
            id = row.getAttribute('typeID')
            queue.append({
                'level':row.getAttribute('level'),
                'end':  row.getAttribute('endTime'),
            })
            last = queue[-1]
            self.queue.append('|'.join([id, last['level'], last['end']]))
            if id in skills:
                skills[id].append(last)
            else:
                skills[id] = [last]

        if queue:
            self.queueEnd = parseEveDateTime(queue[-1]['end'])
        else:
            self.queueEnd = datetime.datetime.utcnow()

        self.put()

        for id, name in Skill.getNames(skills.keys()).items():
            for rec in skills[id]:
                rec['name'] = name

        return queue

    def getQueueCached(self):
        skills = {}
        queue = []
        for line in self.queue:
            rec = {}
            (id, rec['level'], rec['end']) = line.split('|')
            queue.append(rec)
            if id in skills:
                skills[id].append(rec)
            else:
                skills[id] = [rec]

        for id, name in Skill.getNames(skills.keys()).items():
            for rec in skills[id]:
                rec['name'] = name

        return queue

class MainPage(webapp.RequestHandler):
    def get(self):
        user = users.get_current_user()
        if user:
            self.response.out.write("Hello, %s " % user.nickname())
            self.response.out.write('<a href="%s">logout</a>' % users.create_logout_url(self.request.uri))
        else:
            self.response.out.write('<a href="%s">login</a>' % users.create_login_url(self.request.uri))
            return

        self.response.out.write('<hr><ul>')
        for char in Character.gql("WHERE owner=:1", users.get_current_user()):
            self.response.out.write('<li><a href="/char?action=view&charID=%s">%s</a></li>' % (
                char.key().name(), char.name))
        self.response.out.write('<li><a href="/char?action=add">Add another character</a></li></ul>')

messages = [None]*24
messages[0] = "Warning: Your skill queue will expire in %s which is less than 1 hour."
messages[11] = "Reminder: Your skill queue will expire in %s which is less than 12 hours."
messages[23] = "Information: Your skill queue will expire in %s. You can now add a skill to your queue."

class CharHandler(webapp.RequestHandler):
    def get(self):
        action = self.request.get('action')
        if action == 'view':
            return self.view()
        if action == 'add':
            return self.new()

    def post(self):
        action = self.request.get('action')
        if action == 'do_add':
            return self.add()

    def new(self):
        if not users.get_current_user():
            self.redirect(users.create_login_url(self.request.uri))
        self.response.out.write('''<form action="/char" method="post">
<input type="hidden" value="do_add" name="action">
userID: <input type="text" name="acctID"><br>
apiKey: <input type="text" name="apiKey"><br>
characterID: <input type="text" name="charID">
<input type="submit"> <a href="/">Cancel</a>''')

    def add(self):
        charID = self.request.get('charID')

        account = Account.get_or_insert(self.request.get('acctID'))

        if Character.get_by_key_name(charID):
            self.response.out.write("Specified character already exists.<hr>");
        else:
            character = Character(key_name = charID)
            character.acct = account
            character.apiKey = self.request.get('apiKey')
            data = fetch(EVE_URI+API_PATHS['CharName'], method='POST', payload='ids=%s' % charID)
            doc = parseString(data.content)
            character.name = doc.getElementsByTagName('row')[0].getAttribute('name')
            character.ID = int(charID)
            tick = Tick.registerCharacter(character)
            character.put()
            self.response.out.write("Successfully added character %s to tick %d<hr>" % (character.name, tick))

        self.response.out.write('<a href="/">Back to main</a>')

    def view(self):
        try:
            character = Character.getByID(self.request.get('charID'))
        except Exception as exc:
            self.response.out.write("Error: %s" % exc);
            return

        queue = character.getQueue()

        qlen = character.queueEnd - datetime.datetime.utcnow()
        if qlen.days > 0:
            message = None
        elif qlen.days < 0:
            message = "<font color='red'>The queue is empty!</font>"
        else:
            message = messages[23] % timeDiffToStr(qlen.seconds)

        template_values = {
            'char': character,
            'skills': queue,
            'message': message,
        }        

        path = os.path.join(os.path.dirname(__file__), 'queue.html')
        self.response.out.write(template.render(path, template_values))

class Tick(db.Model):
    pos = db.IntegerProperty()
    num = db.IntegerProperty()
    chars = db.ListProperty(int)
    @staticmethod
    def registerCharacter(char):
        usedTicks = Tick.all().count(60)
        if usedTicks < 60: # got some empty ticks
            tick = Tick(pos=usedTicks, num = 0)
        else:
            tick = Tick.gql("order by num").get()
        tick.chars.append(char.ID)
        tick.num += 1
        tick.put()
        return tick.pos

class Checker(webapp.RequestHandler):
    def get(self):
        return

def check(charID):
    try:
        character = Character.getByID(charID)
    except:
        return

    if not character.owner.email(): # nothing we can do
        return

    hours = (character.queueEnd - datetime.datetime.utcnow()).seconds // (60*60)
    if hours < 24 and messages[hours]:
        mail.send_mail(sender="aragaer@gmail.com",
                    to=character.owner.email(),
                    subject="Skill Queue",
                    body=messages[hours] % timeDiffToStr(qlen))
    else:
        mail.send_mail(sender="aragaer@gmail.com",
                    to=character.owner.email(),
                    subject="Skill Queue",
                    body='Hourly check')


application = webapp.WSGIApplication([
  ('/', MainPage),
  ('/char', CharHandler),
  ('/tick', Checker)
], debug=True)

# handy stuff
def timeDiffToStr(s):
    h = s // (60*60)
    s %= 60*60
    m = s // 60
    s %= 60
    return "%dh, %dm, %ds" % (h, m, s)

def parseEveDateTime(value):
    return datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")

def main():
    run_wsgi_app(application)


if __name__ == '__main__':
    main()
