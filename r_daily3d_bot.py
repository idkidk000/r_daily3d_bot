import praw
import threading
import queue
import datetime
import time
import re
import random
import sys
import string

# reddit's search is now shit - https://www.reddit.com/r/changelog/comments/7tus5f/update_to_search_api/
# this means that subreddit.search() now sometimes returns results which are up to an hour out of date
# they also removed the api endpoint which allowed you to get posts by subreddit
# it shouldn't affect the bot in production, given that it will only be posting daily

reddit_account = ('USERNAME', 'PASSWORD') #credentials
reddit_user_agent='Daily3D_Bot/1.0' #can be anything tbh
reddit_client_id='CLIENT_ID' # from https://www.reddit.com/prefs/apps/
reddit_client_secret='CLIENT_SECRET' #from https://www.reddit.com/prefs/apps/

log_file_name_prefix = 'Daily3D_Bot-'
log_file_name_append_isodate = True # append isodate to log_file_name_prefix
log_file_extension = '.log' # log file extension

submit_users_mods = True # allow all mods of $post_sub to submit themes
submit_users_extra = [] # extra users

submit_subject_daily = 'Daily' # received PMs with this subject are determined to be a list of daily themes
submit_subject_weekly = 'Weekly' # received PMs with this subject are determined to be a list of weekly themes

submit_invalid_message = 'I didn\'t recognise your message subject. Please use either "Daily" or "Weekly" to identify the type of topics you\'re submitting.'
submit_unauth_message = 'You\'re not allowed to do that.'

cache_subreddit = 'Daily3D_Cache' # sub in which themes are stored
cache_alert_daily = 5 # alert is triggered when count of daily themes in cache sub is equal to or less than this value
cache_alert_weekly = 2 # alert is triggered when count of weekly themes in cache sub is equal to or less than this value
cache_alert_users_mods = False # alert all mods of $post_sub when alert is triggered
cache_alert_users_extra = ['wilhelm_iii','poopcoptor'] # extra users

upvote_worker_sleep_secs_min = 2 * 60
upvote_worker_sleep_secs_max = 15 * 60 #sleeps for a random inteerval between these two values between queue size checks

post_subreddit = 'Daily3D_Bot' # sub in which to post threads and upvote replies
post_hour_utc = 4
post_minute_utc = 0
post_day_weekly = 7 # iso weekday: mon = 1, sun = 7
post_retry_seconds = 30 # retry every n seconds if posting fails

# subjects and stickying settings for our posts
post_subject_daily = 'Daily3D#$post_id—$post_theme'
post_subject_weekly = 'Weekly Theme Post#$post_id—$post_theme'
post_subject_suggestion = 'Weekly Suggestion Thread#$post_id$post_theme'
post_sticky_daily = False
post_sticky_weekly = True
post_sticky_suggestion = True
post_body_template = 'Suggested by $suggested_by.'

# disable parts of the script for debugging
enable_messaging_worker = True
enable_posting_worker = True
enable_voting_worker = True

# queues. these should be private to the classes, and those classes should be single-instance, but I have no idea how to do that in python
voting_queue = queue.Queue()

# metaclass containing threading and a praw instance (praw handles timeouts and disconnects but is not theadsafe)
class RedditThread(threading.Thread):
    def __init__(self):
        self.reddit = praw.Reddit(
            user_agent=reddit_user_agent,
            client_id=reddit_client_id,
            client_secret=reddit_client_secret,
            username=reddit_account[0],
            password=reddit_account[1]
        )
        threading.Thread.__init__(self)

# PM listener
class Messaging(RedditThread):
    def run(self):
        while True:
            try:
                log('Messaging : run : start')
                
                # generate list of submit_users
                if submit_users_mods:
                    submit_users = [str(mod) for mod in self.reddit.subreddit(post_subreddit).moderator()]
                else:
                    submit_users = []
                submit_users += submit_users_extra
                
                log('Messaging : run : submit_users :', str(submit_users))
                
                # loop through all PMs
                for inbox_message in self.reddit.inbox.stream(): # this returns existing and new messages as they arrive

                    # already read
                    if not inbox_message.new:
                        # pointless to logspam
                        pass

                    # PM
                    elif isinstance(inbox_message, praw.models.Message): 
                        # authorized
                        if str(inbox_message.author) in submit_users:
                            # valid subject
                            if inbox_message.subject in (submit_subject_daily, submit_subject_weekly):
                                log('Messaging : run: message : auth : valid :', inbox_message.id, ':', str(inbox_message.author), ':', inbox_message.subject)

                                # loop through the received themes and store in $cache_subreddit if they're not duplicates
                                accepted_count = 0
                                duplicate_count = 0
                                #for request_theme_raw in re.split(';|\.|,|\*|\n',inbox_message.body):
                                for request_theme_raw in inbox_message.body.split('\n'): # allow crediting users
                                    request_theme=request_theme_raw.split('/u/')[0].strip()
                                    try:
                                        request_suggested_by=request_theme_raw.split('/u/')[1].strip()
                                    except:
                                        request_suggested_by=''
                                        
                                    if request_suggested_by != '':
                                        request_suggested_by='/u/'+request_suggested_by
                                    if len(request_theme)>0: #whitespace and other nonsense
                                        is_duplicate = False
                                        for cached_theme in self.reddit.subreddit(cache_subreddit).search(inbox_message.subject+' '+request_theme,sort='new'):
                                            if cached_theme.title == inbox_message.subject+' '+request_theme:
                                                log('Messaging : run : message : auth : valid : theme already exists :', inbox_message.subject, ':', request_theme, ':', cached_theme.shortlink)
                                                is_duplicate = True
                                        if not is_duplicate:
                                            cached_theme = self.reddit.subreddit(cache_subreddit).submit(inbox_message.subject+' '+request_theme,request_suggested_by)
                                            accepted_count += 1
                                            log('Messaging : run : message : auth : valid : theme cached :', inbox_message.subject, ':', request_theme, ':', cached_theme.shortlink)
                                        else:
                                            duplicate_count += 1
                                inbox_message.reply('Received ' + str(accepted_count+duplicate_count) + ' ' + inbox_message.subject + ' themes.\n\n' + str(accepted_count) + ' accepted, ' + str(duplicate_count) + ' duplicates.')
                            # invalid subject
                            else:
                                log('Messaging : run: message : auth : invalid subject :', inbox_message.id, ':', str(inbox_message.author), ':', inbox_message.subject)
                                inbox_message.reply(submit_invalid_message)
                            
                        # unauthorized
                        else:
                            log('Messaging : run : message : unauth :', inbox_message.id, ':', str(inbox_message.author), ':', inbox_message.subject)
                            try:
                                inbox_message.reply(submit_unauth_message)
                            except:
                                pass # don't really care if this fails
                        
                        # mark read so that we don't try to reprocess
                        inbox_message.mark_read()
                    
                    # Submission reply
                    elif isinstance(inbox_message, praw.models.Comment):
                        log('Messaging : run : comment :', inbox_message.id, str(inbox_message.author))
                        Voting.queue(inbox_message.id)
                        
                        # mark read so that we don't try to reprocess
                        inbox_message.mark_read()                
                        
                    # invalid message type
                    else:
                        log('Messaging : run : not message : error : received invalid message type :', type(inbox_message))

            except BaseException as e:
                log('Messaging : run :', 'line {} :'.format(sys.exc_info()[-1].tb_lineno), 'exception {!r} :'.format(e), 'restarting thread')

# lazy voting. reddit ignores immediate votes (i.e. if we just sat on self.queue.get()), so just leave items enqueued and vote after a random timeframe
class Voting(RedditThread):
    def queue(comment_id):
        voting_queue.put(comment_id)
    
    def run(self):
        while True:
            try:
                log('Voting : run : start')
                while True:                
                    if not voting_queue.empty():
                        log('Voting: run : queue length :', voting_queue.qsize)
                        while not self.queue.empty():
                            comment_id = voting_queue.get()
                            comment = praw.models.Comment(self.reddit, id=comment_id)
                            comment.upvote()
                            log('Voting : run : upvote:', comment.shortlink)

                    sleep_seconds = random.randint(upvote_worker_sleep_secs_min, upvote_worker_sleep_secs_max)
                    time.sleep(sleep_seconds)            

            except BaseException as e:
                log('Voting : run :', 'line {} :'.format(sys.exc_info()[-1].tb_lineno), 'exception {!r} :'.format(e), 'restarting thread')
                
class Posting(RedditThread):
    def __post(self, type):
        log('Posting : post :',type)
        success = False
        while not success: # keep retrying until successful
            try:
                #TODO: type needs to be a class so that int/subject/label lookups are handled in one place
                if type == 'Daily':
                    post_subject_template = post_subject_daily
                    post_sticky = post_sticky_daily
                elif type =='Weekly':
                    post_subject_template = post_subject_weekly
                    post_sticky = post_sticky_weekly
                elif type == 'Suggestion':
                    post_subject_template = post_subject_suggestion
                    post_sticky = post_sticky_suggestion
                
                search_term = post_subject_template.split('#')[0] #post subject up to the #
                log('Posting : post :', type, ': search :', search_term)
                
                active_post = self.reddit.subreddit(post_subreddit).search(search_term,sort='new').next() #search for the newest post with our search term
                log('Posting : post :', type, ': active :', active_post.title, ':',active_post.shortlink)
                    # '{} UTC'.format(time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(active_post.created_utc))))
                
                active_id = int(active_post.title[len(search_term)+1:].split('-')[0].split('—')[0]) #id is between # and - or —
                new_id = active_id+1
                log('Posting : post :', type, ': id last {}'.format(active_id), ': id new {}'.format(new_id))
                
                if type in ('Daily', 'Weekly'):
                    #pull all available themes into a list. we need the actual post object rather than a string so that we can delete it later
                    post_themes = [theme for theme in self.reddit.subreddit(cache_subreddit).search(type,sort='new') if theme.title[:len(type)]==type] #sort new seems to avoid a caching bug in praw
                    log('Posting : post :', type, ': id {}'.format(new_id),': {} themes in cache'.format(len(post_themes)))
                    
                    #throw an exception if there are no themes
                    assert(len(post_themes)>0)
                    
                    #select one at random
                    post_theme = post_themes[random.randint(0,len(post_themes)-1)]
                    post_theme_string = post_theme.title[len(type)+1:]
                    
                    if len(post_theme.selftext)>0:
                        post_body = string.Template(post_body_template).substitute(suggested_by=post_theme.selftext.strip())
                    else:
                        post_body = ''
                else:
                    post_theme_string=''
                    post_body = ''
                log('Posting : post : theme:', post_theme_string)
                
                # build the title from the template and submit it
                post_title = string.Template(post_subject_template).substitute(post_id=new_id, post_theme=post_theme_string)
                log('Posting : post :', post_title)
                new_post = self.reddit.subreddit(post_subreddit).submit(post_title, post_body)

                #delete the cached theme now that we've used it
                try:
                    post_theme.delete()
                    post_theme.mod.remove() # .delete() won't work on cache posts which we didn't submit, so fall back to mod.remove()
                except NameError:
                    pass
                    # post_theme won't be set for suggestion posts. there's probably a better way to check for this
                    
                
                # unsticky the old post and sticky the new one if enabled
                if post_sticky:
                    log('Posting : post : unsticky :', active_post.title, ':', active_post.shortlink)
                    active_post.mod.sticky(state=False)
                    log('Posting : post : sticky :', new_post.title, ':', new_post.shortlink)
                    new_post.mod.sticky()
                else:
                    log('Posting : post : not stickying :', new_post.title, ':', new_post.shortlink)
                
                # this exits the loop and lets the function return
                success = True
                
            except BaseException as e:
                log('Posting : __post :', 'line {} :'.format(sys.exc_info()[-1].tb_lineno), 'exception {!r} :'.format(e), 'retrying in {} seconds'.format(post_retry_seconds))
                time.sleep(post_retry_seconds)

    def run(self):
        log('Posting : run : start')
        while True:
            try:
                while True:
                    now = datetime.datetime.utcnow()
                    post_time = datetime.datetime(now.year, now.month, now.day, post_hour_utc, post_minute_utc)
                    if post_time < now:
                        post_time += datetime.timedelta(days=1)
                        
                    # heroku might sleep our session and make a long sleep unreliable, so sleep for short incremements until it's time to post
                    while datetime.datetime.utcnow() < post_time:
                        time.sleep(60)
                        
                    # post
                    self.__post('Daily')
                    if datetime.datetime.today().isoweekday() == post_day_weekly:
                        self.__post('Weekly')
                        self.__post('Suggestion')
                        
                    # get the cache levels and send alerts
                    if cache_alert_users_mods:
                        cache_alert_users = [str(mod) for mod in self.reddit.subreddit(post_subreddit).moderator()]
                    else:
                        cache_alert_users = []
                    cache_alert_users += cache_alert_users_extra
                    
                    daily_cache_count = len([theme for theme in self.reddit.subreddit(cache_subreddit).search('Daily',sort='new') if theme.title[:5] == 'Daily' ])
                    weekly_cache_count = len([theme for theme in self.reddit.subreddit(cache_subreddit).search('Weekly',sort='new') if theme.title[:6] == 'Weekly' ])
                    
                    alert_caches = []
                    if daily_cache_count <= cache_alert_daily:
                        alert_caches.append('Daily')
                    
                    if weekly_cache_count <= cache_alert_weekly:
                        alert_caches.append('Weekly')
                    
                    if not alert_caches == []:
                        alert_subject = '/r/Daily3D theme caches are running low. Daily: ' + str(daily_cache_count) + ', weekly: ' + str(weekly_cache_count) + '.'
                        alert_body = 'Please PM me additional themes in list format using either "Daily" or "Weekly" as the message subject.\n\nYou can optionally credit theme submitters by putting /u/username on the same line as the theme.'                        
                        for cache_alert_user in cache_alert_users:
                            log('Posting : run : cache alert :', cache_alert_user, alert_subject)
                            self.reddit.redditor(cache_alert_user).message(alert_subject, alert_body)

            except BaseException as e:
                log('Posting : run :', 'line {} :'.format(sys.exc_info()[-1].tb_lineno), 'exception {!r} :'.format(e), 'restarting thread')
                       
def main():
    log('main : starting up')
    threads=[]

    if enable_messaging_worker:
            threads.append(Messaging())
    if enable_posting_worker:
            threads.append(Posting())
    if enable_voting_worker:
            threads.append(Voting())
            
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
        
# simple logger
def log(a, *args):
    log_text = str( datetime.datetime.time(datetime.datetime.now())) + ' ' + str(a)
    for arg in args:
        log_text+=' '+str(arg)
    print(log_text)
    if log_file_name_append_isodate:
        log_file_name = log_file_name_prefix + str(datetime.date.today()) + log_file_extension
    else:
        log_file_name = log_file_name_prefix + log_file_extension
    log_file = open(log_file_name, 'a')
    log_file.write(log_text+'\n')
    log_file.close()

if __name__ == '__main__':
    main()
