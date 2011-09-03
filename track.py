import cgi, datetime, urllib, wsgiref.handlers, os, logging

from google.appengine.ext import db, webapp
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
        template_values = {
            'login_url':users.create_login_url(self.request.uri),
        }
        if user:
            template_values['name'] = user.nickname()
            template_values['chars'] = account.get_my_characters()

        path = os.path.join(os.path.dirname(__file__), 'welcome.html')
        self.response.out.write(template.render(path, template_values))

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
        else:
            self.redirect('/')

    def post(self):
        action = self.request.get('action')
        if action == 'add_key':
            return self.add_key()
        else:
            self.redirect('/')

    def new(self):
        path = os.path.join(os.path.dirname(__file__), 'add.html')
        self.response.out.write(template.render(path, {}))

    def add_key(self):
        keyID = self.request.get('keyID')
        vCode = self.request.get('vCode')

        template_values = {'chars': [], 'msg': []}
        try:
            keyInfo = account.api.account.APIKeyInfo(keyID=keyID, vCode=vCode).key
            if not keyInfo.accessMask & 0x40000:
                raise Exception("Supplied key doesn't allow access to skill queue data.")
            if keyInfo.accessMask ^ 0x40000:
                template_values['msg'].append("The key you supplied allows access not just to skill queue.")

            acct = account.try_add_account(int(keyID), self.request.get('vCode'))
            for char in keyInfo.characters:
                try:
                    acct.add_character(char.characterID, char.characterName)
                    template_values['chars'].append(char.characterName)
                except Exception, exc:
                    template_values['msg'].append("%s" % exc)
                    logging.info("Adding character %s %d: %s" % (char.characterName, char.characterID, exc))
            path = os.path.join(os.path.dirname(__file__), 'added.html')
            self.response.out.write(template.render(path, template_values))
        except Exception, exc:
            msg = "Error adding/getting account %s: %s" % (keyID, exc)
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
            if not acct or not acct.owner.email(): # nothing we can do
                continue
            (training, qEnd) = acct.check_queue()
            qlen = qEnd - datetime.datetime.utcnow()
            hours = qlen.seconds // (60*60)
            if qlen.days == 0 and MESSAGES[hours]:
                mail.send_mail(sender=SENDER,
                            to=acct.owner.email(),
                            subject="Skill Queue for %s" % training.name,
                            body=MESSAGES[hours] % timeDiffToStr(qlen.seconds))
            else:
                logging.info("Hourly check for acct %d (%s is training at least %d days)" % (
                        acct.ID, training.name, qlen.days))

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
