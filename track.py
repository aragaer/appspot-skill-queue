import cgi, datetime, urllib, wsgiref.handlers, os, logging

from google.appengine.ext import db, webapp, deferred
from google.appengine.api import users, mail
from google.appengine.ext.webapp.util import run_wsgi_app

from google.appengine.ext.webapp import template
from google.appengine.api.app_identity import get_application_id

import account
from tick import Tick

SENDER="noreply@%s.appspotmail.com" % get_application_id()

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
        for char in account.get_my_characters():
            self.response.out.write('<li><a href="/char?action=view&charID=%s">%s</a></li>' % (
                char.ID, char.name))
        self.response.out.write('<li><a href="/char?action=add">Add another character</a></li></ul>')

MESSAGES = [None]*24
MESSAGES[1] = "Warning: Your skill queue will expire in %s which is less than 2 hours."
MESSAGES[11] = "Reminder: Your skill queue will expire in %s which is less than 12 hours."
MESSAGES[23] = "Information: Your skill queue will expire in %s. You can now add a skill to your queue."

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
        acctID = self.request.get('acctID')

        try:
            acct = account.try_add_account(int(acctID), self.request.get('apiKey'))
            character = acct.add_character(int(charID))
            self.response.out.write("Successfully added character %s<hr>" % character.name)
        except Exception, exc:
            msg = "Error adding/getting account %s: %s" % (acctID, exc)
            logging.error(msg)
            self.response.out.write('%s<br>' % msg)

        self.response.out.write('<a href="/">Back to main</a>')

    def view(self):
        charID = self.request.get('charID')
        try:
            character = account.get_character_by_id_secure(int(charID))

            queue = character.getQueue()

            acct = character.acct
            qlen = acct.queueEnd - datetime.datetime.utcnow()
            if acct.training.ID == character.ID:
                if qlen.days > 0:
                    message = None
                elif qlen.days < 0:
                    message = "<font color='red'>The queue is empty!</font>"
                else:
                    message = MESSAGES[23] % timeDiffToStr(qlen.seconds)
            else:
                acct.training.refreshQueue()
                qlen = acct.queueEnd - datetime.datetime.utcnow()
                if qlen.days < 0:
                    message = "<font color='red'>The queue is empty!</font>"
                else:
                    message = "Currently training on this account: %s. The queue will expire in %dd, %s." % (
                        acct.training.name, qlen.days, timeDiffToStr(qlen.seconds))

            template_values = {
                'char': character,
                'skills': queue,
                'message': message
            }

            path = os.path.join(os.path.dirname(__file__), 'queue.html')
            self.response.out.write(template.render(path, template_values))
        except Exception, exc:
            msg = "Error viewing character %s: %s" % (charID, exc)
            self.response.out.write('%s<br><a href="/">Back to main</a>' % msg)
            logging.error(msg)

class Checker(webapp.RequestHandler):
    def get(self):
        if self.request.get('ticknum'):
            ticknum = int(self.request.get('ticknum'))
        else:
            ticknum = datetime.datetime.utcnow().minute
        tick = Tick.gql("WHERE pos = :1", ticknum).get()
        if not tick:
            return
        for acct in account.Account.get(tick.accts):
            if acct and acct.owner.email():
                deferred.defer(check_and_notify, acct.ID)

def check_and_notify(acctID):
    acct = account.Account.get(acctID)
    (training, qEnd) = acct.check_queue()
    qlen = qEnd - datetime.datetime.utcnow()
    hours = qlen.seconds // (60*60)
    if qlen.days == 0 and MESSAGES[hours]:
        mail.send_mail(sender=SENDER,
                       to=acct.owner.email(),
                       subject="Skill Queue for %s" % training.name,
                       body=MESSAGES[hours] % timeDiffToStr(qlen.seconds))
    elif training:
        logging.info("Hourly check for acct %d (%s is training at least %d days)" % (
                    acct.ID, training.name, qlen.days))
    else:
        logging.info("Hourly check for acct %d (queue empty)" % acct.ID)

application = webapp.WSGIApplication([
  ('/', MainPage),
  ('/char', CharHandler),
  ('/tick/', Checker)
], debug=True)

# handy stuff
def timeDiffToStr(s):
    h = s // (60*60)
    s %= 60*60
    m = s // 60
    s %= 60
    return "%dh, %dm, %ds" % (h, m, s)

def main():
    run_wsgi_app(application)

if __name__ == '__main__':
    main()
