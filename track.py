import cgi, datetime, urllib, wsgiref.handlers, os, urllib, time

from google.appengine.ext import db, webapp
from google.appengine.api import users, mail
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api.urlfetch import fetch
from xml.dom.minidom import parseString

from google.appengine.ext.webapp import template
from time import strptime
from calendar import timegm

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

class Account(db.Model):
    owner = db.UserProperty(auto_current_user_add=True)

class Character(db.Model):
    acct = db.ReferenceProperty(Account)
    apiKey = db.StringProperty()
    name = db.StringProperty()
    owner = db.UserProperty(auto_current_user_add=True)
    ID = db.IntegerProperty

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

class Char(webapp.RequestHandler):
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
            character.put()
            self.response.out.write("Successfully added character %s<hr>" % character.name)

        self.response.out.write('<a href="/">Back to main</a>')

    def view(self):
        character = Character.get_by_key_name(self.request.get('charID'))
        if not character:
            self.response.out.write("Error: No such character")
            return
        if character.owner != users.get_current_user():
            self.response.out.write("Error: Wrong owner")
            return

        character.ID = character.key().name()

        args = urllib.urlencode({
            'userID': character.acct.key().name(),
            'apiKey': character.apiKey,
            'characterID': character.ID
        })
        data = fetch(EVE_URI+API_PATHS['SkillQueue'], method='POST', payload=args)
        doc = parseString(data.content)
        queue = []
        skills = {}
        for row in doc.getElementsByTagName('row'):
            id = row.getAttribute('typeID')
            queue.append({
                'id':   id,
                'level':row.getAttribute('level'),
                'end':  row.getAttribute('endTime'),
            })
            skills[id] = None

        for skill in Skill.get_by_key_name(skills.keys()):
            if not skill:
                continue
            id = skill.key().name()
            del skills[id]
            for item in queue:
                if item['id'] == id:
                    item['name'] = skill.name

        if skills:
            data = fetch(EVE_URI+API_PATHS['SkillName'], method='POST', payload='ids=%s' % ','.join(skills.keys()))
            doc = parseString(data.content)
            for row in doc.getElementsByTagName('row'):
                id = row.getAttribute('characterID')
                name = row.getAttribute('name')
                skill = Skill(key_name=id, name=name)
                skill.put()
                for item in queue:
                    if item['id'] == id:
                        item['name'] = skill.name

        if queue:
            end = max(0, int(timegm(strptime(queue[-1]['end'], "%Y-%m-%d %H:%M:%S"))))
            qlen = end - time.time()
            if qlen > 24*60*60:
                message = "Everything's ok"
            else:
                message = "The queue expires in %s. You can now add a skill to queue." % timeDiffToStr(qlen)
        else:
            message = "<font color='red'>The queue is empty!</font>"

        template_values = {
            'char': character,
            'skills': queue,
            'message': message,
        }        

        path = os.path.join(os.path.dirname(__file__), 'queue.html')
        self.response.out.write(template.render(path, template_values))

        if character.owner.email():
            mail.send_mail(sender="aragaer@gmail.com",
                        to=character.owner.email(),
                        subject="Skill Queue",
                        body=message)


application = webapp.WSGIApplication([
  ('/', MainPage),
  ('/char', Char)
], debug=True)

# handy stuff
def timeDiffToStr(s):
    h = s // (60*60)
    s -= h * 60*60
    m = s // 60
    s -= m * 60
    return "%dh, %dm, %ds" % (h, m, s)

def main():
    run_wsgi_app(application)


if __name__ == '__main__':
    main()
