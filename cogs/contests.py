import discord
from discord.ext import commands, tasks
import os
from time import time
import random as rand
from datetime import datetime, timedelta
import json
import bs4 as bs
import pytz
from connector import mySQLConnection as query
from utils.onlinejudges import OnlineJudges, NoSuchOJException
from utils.webclient import webc


class Contest(object):
    def __init__(self, data):
        self.data = data

    def asdict(self):
        return self.data

    def __eq__(self, other):
        if self.data['oj'] == 'topcoder' and other.data['oj'] == 'topcoder':
            return self.data['title'] == other.data['title']
        return self.data['description'] == other.data['description']

    def __gt__(self, other):
        if self.data['oj'] == 'topcoder' and other.data['oj'] == 'topcoder':
            return self.data['title'] > other.data['title']
        return self.data['description'] > other.data['description']

    def __str__(self):
        if self.data['oj'] == 'topcoder':
            return self.data['title']
        return self.data['description']

    def __hash__(self):
        return hash(str(self))

class NoContestsAvailableException(Exception):

    onlineJudges = OnlineJudges()

    def __init__(self, oj=None):
        self.oj = oj

    def __str__(self):
        if self.oj is None:
            return 'Sorry, there are not upcoming contests currently available.'
        return 'Sorry, there are not upcoming contests from %s currently available.' % self.onlineJudges.formal_names[self.oj]

class ContestCog(commands.Cog):
    fetch_time = 0

    dmoj_contests = []
    cf_contests = []
    atcoder_contests = []
    leetcode_contests = []
    codechef_contests = []
    topcoder_contests = []

    contest_objects = []

    onlineJudges = OnlineJudges()

    def __init__(self, bot):
        self.bot = bot

        if not os.path.isfile('data/contests.json'):
            with open('data/contests.json', 'w+', encoding='utf8', errors='ignore') as f:
                json.dump([], f)

        with open('data/contests.json', 'r', encoding='utf8', errors='ignore') as f:
            prev_contest_data = json.load(f)
            self.contest_cache = []
            for data in prev_contest_data:
                self.contest_cache.append(Contest(data))

        self.refresh_contests.start()

    def get_random_contests(self, number):
        upcoming_contests = list(filter(self.is_upcoming, self.contest_cache))
        if len(upcoming_contests) == 0:
            raise NoContestsAvailableException()
        rand.shuffle(upcoming_contests)
        result = []
        for i in range(min(number, len(upcoming_contests))):
            result.append(upcoming_contests[i])
        return self.embed_multiple_contests(result)

    def get_contests_of_oj(self, oj):
        upcoming_contests = list(filter(self.is_upcoming, self.contest_cache))
        result = []
        for contest_object in upcoming_contests:
            if oj == contest_object.asdict()['oj']:
                result.append(contest_object)
        if len(result) == 0:
            raise NoContestsAvailableException(oj)
        return self.embed_multiple_contests(result, oj)

    def reset_contest(self, oj):
        if oj == 'dmoj':
            self.dmoj_contests = []
        elif oj == 'codeforces':
            self.cf_contests = []
        elif oj == 'atcoder':
            self.atcoder_contests = []
        elif oj == 'codechef':
            self.codechef_contests = []
        elif oj == 'topcoder':
            self.topcoder_contests = []

    def set_time(self):
        self.fetch_time = time()

    async def parse_dmoj_contests(self):
        contest_req = await webc.webget_json('https://dmoj.ca/api/v2/contests')
        contests = contest_req['data']['objects']
        for details in contests:
            name = details['key']
            if datetime.strptime(details['start_time'].replace(':', ''), '%Y-%m-%dT%H%M%S%z').timestamp() > time():
                spec = webc.webget_json('https://dmoj.ca/api/v2/contest/' + name)['data']['object']
                url = 'https://dmoj.ca/contest/' + name
                contest_data = {
                    'title': ':trophy: %s' % details['name'],
                    'description': url,
                    'oj': 'dmoj',
                    'Start Time': datetime.strptime(details['start_time'].replace(':', ''), '%Y-%m-%dT%H%M%S%z').strftime('%Y-%m-%d %H:%M:%S%z'),
                    'End Time': datetime.strptime(details['end_time'].replace(':', ''), '%Y-%m-%dT%H%M%S%z').strftime('%Y-%m-%d %H:%M:%S%z')
                }
                if spec['time_limit'] is not None:
                    contest_data['Window'] = '%d:%d:%d' % (spec['time_limit']//(60*60), spec['time_limit']%(60*60)//60, spec['time_limit']%60)
                if len(spec['tags']) > 0:
                    contest_data['Tags'] = ', '.join(spec['tags'])
                contest_data['Rated'] ='Yes' if spec['is_rated'] else 'No'
                contest_data['Format'] = spec['format']['name']
                self.dmoj_contests.append(Contest(contest_data))
        self.dmoj_contests = list(set(self.dmoj_contests))

    async def parse_cf_contests(self):
        contests = await webc.webget_json('https://codeforces.com/api/contest.list')
        for contest in range(len(contests.get('result', []))):
            details = contests['result'][contest]
            if details['phase'] == 'BEFORE':
                url = 'https://codeforces.com/contest/' + str(details['id'])
                contest_data = {
                    'title': ':trophy: %s' % details['name'],
                    'description': url,
                    'oj': 'codeforces',
                    'Type': details['type'],
                    'Start Time': datetime.utcfromtimestamp(details['startTimeSeconds']).strftime('%Y-%m-%d %H:%M:%S%z'),
                    'Duration': '%s:%s:%s' % (str(details['durationSeconds']//(24*3600)).zfill(2), str(details['durationSeconds']%(24*3600)//3600).zfill(2), str(details['durationSeconds']%3600//60).zfill(2))
                }
                self.cf_contests.append(Contest(contest_data))
        self.cf_contests = list(set(self.cf_contests))

    async def parse_atcoder_contests(self):
        contests = await webc.webget_text('https://atcoder.jp/contests/?lang=en')
        soup = bs.BeautifulSoup(contests, 'lxml')
        for contest in soup.find_all('table')[1 + len(soup.find_all('div', attrs={'id': 'contest-table-action'}))].find('tbody').find_all('tr'):
            details = contest.find_all('td')
            if datetime.strptime(details[0].find('a').find('time').contents[0], '%Y-%m-%d %H:%M:%S%z').timestamp() > time():
                contest_data = {
                    'title': ':trophy: %s' % details[1].find('a').contents[0],
                    'description': 'https://atcoder.jp' + details[1].find('a')['href'],
                    'oj': 'atcoder',
                    'Start Time': datetime.strptime(details[0].find('a').find('time').contents[0], '%Y-%m-%d %H:%M:%S%z').strftime('%Y-%m-%d %H:%M:%S%z'),
                    'Duration':  details[2].contents[0] + ':00',
                    'Rated Range': details[3].contents[0]
                }
                self.atcoder_contests.append(Contest(contest_data))
        self.atcoder_contests = list(set(self.atcoder_contests))

    async def parse_leetcode_contests(self):
        contests = await webc.webget_json('https://kontests.net/api/v1/leet_code')
        for contest in contests:
            start_time = datetime.strptime(contest['start_time'].split('.')[0], '%Y-%m-%dT%H:%M:%S').strftime('%Y-%m-%d %H:%M:%S') + '+0000'
            if contest['status'] == 'BEFORE':
                contest_data = {
                    'title': ':trophy: %s' % contest['name'],
                    'description': contest['url'],
                    'oj': 'leetcode',
                    'Start Time': start_time,
                    'End Time': datetime.strptime(contest['end_time'].split('.')[0], '%Y-%m-%dT%H:%M:%S').strftime('%Y-%m-%d %H:%M:%S') + '+0000',
                    'Duration': '%s:%s:%s' % (str(float(contest['duration'])//(24*3600)).zfill(2), str(float(contest['duration'])%(24*3600)//3600).zfill(2), str(float(contest['duration'])%3600//60).zfill(2))
                }
                self.leetcode_contests.append(Contest(contest_data))
        self.leetcode_contests = list(set(self.leetcode_contests))

    async def parse_codechef_contests(self):
        contests = await webc.webget_json('https://kontests.net/api/v1/code_chef')
        for contest in contests:
            if contest['status'] == 'BEFORE':
                contest_data = {
                    'title': ':trophy: %s' % contest['name'],
                    'description': contest['url'].split('?')[0],
                    'oj': 'codechef',
                    'Start Time': datetime.strptime(contest['start_time'].split('.')[0], '%Y-%m-%dT%H:%M:%S').strftime('%Y-%m-%d %H:%M:%S') + '+0000',
                    'End Time': datetime.strptime(contest['end_time'].split('.')[0], '%Y-%m-%dT%H:%M:%S').strftime('%Y-%m-%d %H:%M:%S') + '+0000',
                    'Duration': '%s:%s:%s' % (str(float(contest['duration'])//(24*3600)).zfill(2), str(float(contest['duration'])%(24*3600)//3600).zfill(2), str(float(contest['duration'])%3600//60).zfill(2))
                }
                self.codechef_contests.append(Contest(contest_data))
        self.codechef_contests = list(set(self.codechef_contests))

    async def parse_topcoder_contests(self):
        contests = await webc.webget_json('https://kontests.net/api/v1/top_coder')
        for contest in contests:
            start_time = datetime.strptime(contest['start_time'].split('.')[0], '%Y-%m-%dT%H:%M:%S').strftime('%Y-%m-%d %H:%M:%S') + '+0000'
            if contest['status'] == 'BEFORE' and datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S%z').timestamp() - time() <= 60*60*24*7:
                contest_data = {
                    'title': ':trophy: %s' % contest['name'],
                    'description': contest['url'],
                    'oj': 'topcoder',
                    'Start Time': start_time,
                    'End Time': datetime.strptime(contest['end_time'].split('.')[0], '%Y-%m-%dT%H:%M:%S').strftime('%Y-%m-%d %H:%M:%S') + '+0000',
                    'Duration': '%s:%s:%s' % (str(float(contest['duration'])//(24*3600)).zfill(2), str(float(contest['duration'])%(24*3600)//3600).zfill(2), str(float(contest['duration'])%3600//60).zfill(2))
                }
                self.topcoder_contests.append(Contest(contest_data))
        self.topcoder_contests = list(set(self.topcoder_contests))

    def embed_contest(self, contest):
        embed = discord.Embed(title=contest.asdict()['title'], description=contest.asdict()['description'])
        embed.set_thumbnail(url=self.onlineJudges.thumbnails[contest.asdict()['oj']])
        embed.colour = self.onlineJudges.colours[contest.asdict()['oj']]
        for key in list(contest.asdict().keys()):
            if key not in ('title', 'description', 'oj'):
                embed.add_field(name=key, value=contest.asdict()[key], inline=False)
        return embed

    def embed_multiple_contests(self, contests, oj=None, new=False):
        if len(contests) == 0:
            return None
        if len(contests) == 1:
            return self.embed_contest(contests[0])
        if oj is not None:
            embed = discord.Embed(title='%d %s%s Contests' % (len(contests), ' New' if new else '', self.onlineJudges.formal_names[oj]))
            embed.set_thumbnail(url=self.onlineJudges.thumbnails[oj])
            embed.colour = self.onlineJudges.colours[oj]
        else:
            embed = discord.Embed(title='%d%s Contests' % (len(contests), ' New' if new else ''))
        for contest in sorted(contests):
            embed.add_field(name=contest.asdict()['title'], value=contest.asdict()['description'], inline=(len(contests) > 6))
        return embed
        
    def generate_stream(self):
        self.contest_objects = list(set(self.dmoj_contests + self.cf_contests + self.atcoder_contests + self.leetcode_contests + self.codechef_contests + self.topcoder_contests))

    def update_contest_cache(self):
        with open('data/contests.json', 'w') as json_file:
            prev_contest_data = []
            for contest in self.contest_cache:
                prev_contest_data.append(contest.asdict())
            json.dump(prev_contest_data, json_file)

    @commands.command(aliases=['c'])
    @commands.bot_has_permissions(embed_links=True)
    async def contests(self, ctx, numstr='1'):
        try:
            if numstr == 'all':
                number = len(self.contest_cache)
                contestList = self.get_random_contests(number)
            elif numstr.isdigit():
                number = int(numstr)
                contestList = self.get_random_contests(number)
            elif self.onlineJudges.oj_exists(numstr):
                oj = self.onlineJudges.get_oj(numstr)
                if oj not in self.onlineJudges.contest_judges:
                    await ctx.send(ctx.message.author.display_name + ', Sorry, contests for that site are not available yet or contests are not applicable to that site.')
                    return
                contestList = self.get_contests_of_oj(oj)
            await ctx.send(ctx.message.author.display_name + ', Here are some upcoming contest(s). Last fetched, %d minutes ago' % ((time()-self.fetch_time)//60), embed=contestList)
        except NoContestsAvailableException as e:
            await ctx.send(ctx.message.author.display_name + ', ' + str(e))
        except NoSuchOJException:
            await ctx.send(ctx.message.author.display_name + ', Invalid query. The online judge must be one of the following: %s.' % self.onlineJudges.contest_judges_str())

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    @commands.guild_only()
    async def sub(self, ctx, channel: discord.TextChannel=None):
        determiner = 'That'
        if channel is None:
            channel = ctx.message.channel
            determiner = 'This'
        if query.exists('subscriptions_contests', 'channel_id', channel.id):
            await ctx.send(ctx.message.author.display_name + ', %s channel is already subscribed to contest notifications.' % determiner)
            return
        query.sub_channel(channel.id)
        await ctx.send(ctx.message.author.display_name + ', ' + channel.mention + ' subscribed to contest notifications.')

    @commands.command()
    @commands.guild_only()
    async def subs(self, ctx):
        clist = ctx.message.author.display_name + ', Contest notification channels in this server:\n'
        for text_channel in ctx.message.guild.text_channels:
            if query.exists('subscriptions_contests', 'channel_id', text_channel.id):
                clist += text_channel.mention + '\n'
        if clist == ctx.message.author.display_name + ', Contest notification channels in this server:\n':
            await ctx.send(ctx.message.author.display_name + ', There are no channels subscribed to contest notifications in this server :slight_frown:')
        else:
            await ctx.send(clist)

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    @commands.guild_only()
    async def unsub(self, ctx, channel: discord.TextChannel=None):
        determiner = 'That'
        if channel is None:
            channel = ctx.message.channel
            determiner = 'This'
        if not query.exists('subscriptions_contests', 'channel_id', channel.id):
            await ctx.send(ctx.message.author.display_name + ', %s channel is already not subscribed to contest notifications.' % determiner)
            return
        query.unsub_channel(channel.id)
        await ctx.send(ctx.message.author.display_name + ', ' + channel.mention + ' is no longer a contest notification channel.')

    def is_upcoming(self, contest):
        if '+' in contest.asdict()['Start Time']:
            return datetime.strptime(contest.asdict()['Start Time'], '%Y-%m-%d %H:%M:%S%z') > datetime.now(pytz.UTC)
        return datetime.strptime(contest.asdict()['Start Time'], '%Y-%m-%d %H:%M:%S') > datetime.now()

    def is_recent(self, contest):
        if '+' in contest.asdict()['Start Time']:
            return datetime.strptime(contest.asdict()['Start Time'], '%Y-%m-%d %H:%M:%S%z') > datetime.now(pytz.UTC) - timedelta(days=7)
        return datetime.strptime(contest.asdict()['Start Time'], '%Y-%m-%d %H:%M:%S') > datetime.now() - timedelta(days=7)

    @tasks.loop(minutes=5)
    async def refresh_contests(self):
        try:
            self.reset_contest('dmoj')
            await self.parse_dmoj_contests()
        except:
            pass

        try:
            self.reset_contest('codeforces')
            await self.parse_cf_contests()
        except:
            pass

        try:
            self.reset_contest('atcoder')
            await self.parse_atcoder_contests()
        except:
            pass

        try:
            self.reset_contest('leetcode')
            await self.parse_leetcode_contests()
        except:
            pass

        try:
            self.reset_contest('codechef')
            await self.parse_codechef_contests()
        except:
            pass

        try:
            self.reset_contest('topcoder')
            await self.parse_topcoder_contests()
        except:
            pass
        await self.parse_codechef_contests()
        await self.parse_topcoder_contests()

        self.set_time()
        self.generate_stream()

        new_contests = list(set(self.contest_objects).difference(set(self.contest_cache)))

        for channel_id in query.get_all_subs():
            try:
                channel = self.bot.get_channel(channel_id)
                await channel.send(embed=self.embed_multiple_contests(new_contests, new=True))
            except:
                pass

        self.contest_cache = list(filter(self.is_recent, list(set(self.contest_objects).union(set(self.contest_cache)))))
        self.update_contest_cache()

    @refresh_contests.before_loop
    async def check_contests_before(self):
        await self.bot.wait_until_ready()

def setup(bot):
    bot.add_cog(ContestCog(bot))
