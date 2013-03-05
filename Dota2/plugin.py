###
# Copyright (c) 2013, Anibal Capotorto
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

###

import supybot.utils as utils
from supybot.commands import *
from pymongo import MongoClient
import supybot.plugins as plugins
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks
import time
import urllib2
import json
from threading import Thread

class Dota2Error(Exception): pass

class UserForbidden(Dota2Error):
    msg = "Hay que prender el dota para que pueda ver los datos"

class ValveBusy(Dota2Error):
    msg = "El servidor de valve esta hasta la pija"

class MatchCrawler(Thread):
    def __init__(self,irc,vanityName):
        Thread.__init__(self)
        self.dotaApi = DotaApi()
        self.dotaDB = DotaDB()
        self.irc = irc
        self.vanityName = vanityName
        self.steam32 = self.dotaDB.vanityTo32(vanityName)
        self.gamesRemaining = 0
        self.setName(self.vanityName)
        self.fullGames = None

    def run(self):
        """does all the crawling"""
        self.fullGames = self.dotaDB.getFullMatchesList(self.vanityName)
        if self.fullGames:
            self.gamesRemaining = len(self.fullGames)
            self.irc.reply("Me baje la lista de todos los matches de %s (%s), ahora me bajo la data de esos matches" % (self.vanityName,self.gamesRemaining))
            for game in self.fullGames:
                self.gamesRemaining = self.gamesRemaining - 1
                if not self.dotaDB.getMatch(game):
                    self.irc.relpy("Algo se rompio bajando los matches de %s (no la lista) , vas a tener que correr esto denuevo :(" % self.vanityName)
                    return False
            self.irc.reply("Ya me baje todos los games de %s, asi que ahora podes correr los stats personale!!!!" % self.vanityName)
        else:
            self.irc.reply("No me pude bajar la lista de los matches de %s, se complico vas a tener que correr esto denuevo " % self.vanityName)
        return True
    
class DotaApi():
    apiKey = "<REPLACE WITH YOUR API KEY>"
    magicNumber = 76561197960265728
    lastRequest = time.time()

    def getmatches(self,steam32,startingMatch=None,limit=25):
        """ makes a call to https://api.steampowered.com/IDOTA2Match_570/GetMatchHistory/V001/
        and returns the json data of the result"""
        if limit > 25: limit = 25
        if startingMatch:
            query = "https://api.steampowered.com/IDOTA2Match_570/GetMatchHistory/V001/?account_id=%s&key=%s&start_at_match_id=%smatches_requested=%s" % (steam32,self.apiKey,startingMatch,limit)
        else:
            query = "https://api.steampowered.com/IDOTA2Match_570/GetMatchHistory/V001/?account_id=%s&key=%s&matches_requested=%s" % (steam32,self.apiKey,limit)
        res = self._webcall(query)
        if res.has_key("error"):
            return None
        else:
            if startingMatch:
                res["result"]["matches"].pop(0)
            return res["result"]

    def getheroes(self):
        """gets all the heroes from steam"""
        query = "https://api.steampowered.com/IEconDOTA2_570/GetHeroes/v0001/?language=en_us&key=%s" % self.apiKey
        return self._webcall(query)
   
    def getPlayerBySteam64(self,steam64):
        """queries steam for this guy and returns it's full data"""
        query = "http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?steamids=%s&key=%s" % (steam64,self.apiKey)
        return self._webcall(query)
    
    def getPlayerBySteam32(self,steam32):
        """transforms the steam32 into steam64 and uses getPlayerBySteam64"""
        return self.getPlayerBySteam64(steam32+self.magicNumber)
 
    def getPlayerByName(self,vanityName):
        """gets the player like a champ"""
        query = "http://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/?key=%s&vanityurl=%s" % (self.apiKey,vanityName)
        data = self._webcall(query)
        if data.has_key("error"):
            return None
        else:
            return {"64bits": data["response"]["steamid"],"32bits":data["response"]["steamid"] - self.magicNumber}

    def getMatch(self,matchId):
        """gets the match from the api"""
        match = self._webcall("http://api.steampowered.com/IDOTA2Match_570/GetMatchDetails/V001/?key=%s&match_id=%s" % (self.apiKey,matchId))
        if match.has_key("error"):
            return None
        else:
            return match

    def _webcall(self,query):
        """ makes a get to whatever comes and returns the data or an error """
        if time.time() - DotaApi.lastRequest < 1:
            time.sleep(time.time() - DotaApi.lastRequest)
        DotaApi.lastRequest = time.time()
        try:
            response = urllib2.urlopen(query)
            j = json.loads(response.read())
            try:
                if j["result"]["status"] == 15:
                    raise UserForbidden
            except KeyError:
                pass
        except urllib2.HTTPError as e:
           if e.code == 503: 
              DotaApi.lastRequest = time.time()+30
              raise ValeBusy
           return json.loads("{\"error\": \"%s\", \"html\": \"%s\"}" % (e.code,e.read()))
        return j

class DotaDB:
    def __init__(self):
        self.db = MongoClient().dota2
        self.db.authenticate("<REPLACE WITH YOUR MONGO USER>","<REPLACE WITH YOUR MONGO PASSWORD>")
        self.matches = self.db.matches
        self.heroes = self.db.heroes
        self.players = self.db.players
        self.dotaApi = DotaApi()

    def vanityTo64(self,vanityName):
        """returns the 64 bit steam value thing"""
        player = self.players.find_one({"name":vanityName})
        if not player:
           player = self.createPlayer(vanityName) 
        return int(player["steam64"])

    def vanityTo32(self,vanityName):
        """returns the 32 bit steam value thing"""
        player = self.players.find_one({"name":vanityName})
        if not player:
           player = self.createPlayer(vanityName) 
        return int(player["steam32"])

    def steam32ToVanity(self,steam32,useApi=True):
        """ returns the vanity name of someone """
        if steam32 == 4294967295:
            return "Unknown"
        name = self.players.find_one({"steam32": steam32})
        if name:
            return name["name"]
        if not useApi:
            return False
        apiName = self.dotaApi.getPlayerBySteam32(steam32)
        if apiName:
            return apiName["response"]["players"][0]["personaname"]
        else:
            return False

    def heroIdtoName(self,id):
        """fetches heroes from the database"""
        heroes = self.heroes.find_one()
        if not heroes or int(time.time()) - heroes["lastUpdate"] > 86400:
            res = self.dotaApi.getheroes()
            if not res.has_key("error"):
                self.heroes.remove()
                self.heroes.save({"lastUpdate": int(time.time()), "data": res})
                heroes = self.heroes.find_one()
        for heroe in heroes["data"]["result"]["heroes"]:
            if heroe["id"] == id:
                return heroe["localized_name"]
    
    def createPlayer(self,vanityName,steam64=None):
        """creates the user in the database or updates it for watever reason"""
        if steam64:
            apiPlayer = {"64bits":steam64,"32bits":int(steam64)-76561197960265728}
        else:
            apiPlayer = self.dotaApi.getPlayerByName(vanityName)
        self.db.players.remove({"name":vanityName.lower()})
        self.db.players.save({"name":vanityName,"lastUpdated":int(time.time()),"steam64":apiPlayer["64bits"],"steam32":apiPlayer["32bits"]})
        return self.db.players.find_one({"name":vanityName})
    
    def getMatch(self,matchId):
        """returns the match from the database OR fetches it from the API and stores it on the database"""
        match = self.matches.find_one({"match_id":matchId})
        if not match:
            apiMatch = self.dotaApi.getMatch(matchId)
            if apiMatch.has_key("error"):
                return None
            else:
                self.matches.save({"match_id":matchId,"match_data": apiMatch})
                match = self.matches.find_one({"match_id":matchId})
        return match["match_data"]["result"]

    def getMatches(self,vanityName):
        """ returns an array of matches given the steam vanity name """
        player = self.players.find_one({"name":vanityName})
        if player and player.has_key("matches") and int(time.time()) - player["matches"]["lastUpdate"] < 3600:
            return player["matches"]["data"]
        else:
            matches = self.dotaApi.getmatches(self.vanityTo32(vanityName),None,5)
            if type(matches) is dict and matches.has_key("error"):
                return None
            else:
                self.players.update({"name":vanityName},{"$set": {"matches": { "data": matches["matches"],"lastUpdate": int(time.time())}}})
        return self.players.find_one({"name":vanityName})["matches"]["data"]

    def getFullMatchesList(self,vanityName,download=True):
        """ generates a list in the database of matches """
        needMore = True
        startingMatch = None
        list = self.players.find_one({"name":vanityName})
        if list and list.has_key("fullMatchesList"):
            list = list["fullMatchesList"]
        else:
            list = []
        if not download:
            return list
        while(needMore):
            apiRes = self.dotaApi.getmatches(self.vanityTo32(vanityName),startingMatch,25)
            if apiRes:
                if apiRes["results_remaining"] == 0:
                    needMore = False
                apiList = [x["match_id"] for x in apiRes["matches"]]
                newList = []
                for i in apiList:
                    if list.count(i) == 0:
                        newList.append(i)
                    else:
                        needMore = False
                startingMatch = i
                list = newList + list
            else:
                return False
        self.players.update({"name":vanityName},{"$set" : {"fullMatchesList": list }})
        return list
    
    def matchGamesList(self,list):
        """ returns the full games list"""
        return self.matches.find({"match_id": {"$in": list}})
   
    def wipeGames(self,list):
        """ removes the games from this player from the database"""
        return self.matches.remove({"match_id": {"$in": list}})
 
    def delUser(self,vanityName):
        """ deletes an user from the database"""
        self.players.remove({"name":vanityName})
        return True

class Dota2(callbacks.Plugin):
    def __init__(self,irc):
        self.__parent = super(Dota2, self)
        self.__parent.__init__(irc)
        self.dotaApi = DotaApi()
        self.dotaDB = DotaDB()
        self.jobs = []

    def dotareg(self,irc,msg,args,vanityName,steam64):
        """ dotareg vanityname steam64"""
        vanityName = vanityName.lower()
        self.dotaDB.createPlayer(vanityName,steam64)
        irc.reply("Added")
    dotareg = wrap(dotareg,["anything","anything"])
    
    def getmatches(self,irc,msg,args,vanityName):
        """getmatches vanityname (replace with your actual steam login)
        Use to get the last 25 matches for [vanityname]"""
        vanityName = vanityName.lower()
        try:
            matches = self.dotaDB.getMatches(vanityName)
            steam32 = self.dotaDB.vanityTo32(vanityName)
        except Dota2Error as e:
            irc.reply("Error: %s" % e.msg)
            raise
        irc.reply("Last 5 Matches ID for %s" % vanityName)
        for item in matches[:5]:
            if item.has_key("start_time"):
                for pl in item["players"]:
                    if pl["account_id"] == steam32:
                        break;
                bando = "The Dire" if pl["player_slot"] > 10 else "Radiant"
                irc.reply("Match Id %s as %s playing for %s at %s" % 
                (
                item["match_id"],self.dotaDB.heroIdtoName(pl["hero_id"]),
                bando,time.ctime(item["start_time"]))
                )
            else:
                irc.reply("GG: %s" % item["match_id"])
    getmatches = wrap(getmatches,['text'])

    def addjob(self,irc,msg,args,vanityName):
        """addjob vanityName downloads all the games for vanityname"""
        vanityName = vanityName.lower()
        for x in self.jobs:
            if x.getName() == vanityName:
                if x.isALive():
                    irc.reply("job already running")
                    return True
                else:
                    self.jobs.remove(x)
        t = MatchCrawler(irc,vanityName)
        t.start()
        self.jobs.append(t)
        irc.reply("job added")
    addjob = wrap(addjob,["text"])

    def checkjobs(self,irc,msg,args):
        """ returns the jobs status """
        if self.jobs: 
            for i in self.jobs:
                if i.isAlive():
                    irc.reply("Job %s is running and has %s games to go" % (i.getName(),i.gamesRemaining))
                else:    
                    self.jobs.remove(i)
                    irc.reply("Finished Job removed from list %s" % i)
        else:
            irc.reply("no jobs")
    checkjobs = wrap(checkjobs)

    def nuke(self,irc,msg,args,vanityName):
        """deletes an user"""
        vanityName = vanityName.lower()
        self.dotaDB.delUser(vanityName)
        irc.reply("Fue")
    nuke = wrap(nuke,["text"])

    def nukegames(self,irc,msg,args,vanityName):
        """ nukes games for vanityName """
        vanityName = vanityName.lower()
        self.dotaDB.wipeGames(self.dotaDB.getFullMatchesList(vanityName,False))
        irc.reply("Vole todos los games, addjob %s para que los baje denuevo" % vanityName)
    nukegames = wrap(nukegames,["text"])

    def pstat(self,irc,msg,args,vanityName):
        """ pstat vanityName 
            player Stats"""
        vanityName = vanityName.lower()
        try:
            steam32 = self.dotaDB.vanityTo32(vanityName)
            fullGames = self.dotaDB.matchGamesList(self.dotaDB.getFullMatchesList(vanityName,False))
        except Dota2Error as e:
            irc.reply("Error: %s" % e.msg)
            raise
        kills = deaths = assists = 0.0
        quits = 0
        mostPlayed = {}
        bando = {}
        bando["dire"] = 0
        bando["radiant"] = 0
        radiant_win = dire_win = 0
        if fullGames:
            irc.reply("Stats de %s Games" % fullGames.count())
        for game in fullGames:
            game = game["match_data"]
            player = [x for x in game["result"]["players"] if x["account_id"] == steam32][0]
            kills += player["kills"]
            deaths += player["deaths"]
            assists += player["assists"]
            if player["leaver_status"] == 2:
                quits += 1
            if player["player_slot"] > 10:
                bando["dire"] +=1
                if game["result"]["radiant_win"] == False:
                    dire_win += 1
            else:
                bando["radiant"] +=1
                if game["result"]["radiant_win"] == True:
                    radiant_win += 1
            if mostPlayed.has_key(player["hero_id"]):
                mostPlayed[player["hero_id"]] += 1
            else:
                mostPlayed[player["hero_id"]] = 1
        mPlayed = player["hero_id"]
        for i in mostPlayed:
            if mostPlayed[i] > mostPlayed[mPlayed]:
                mPlayed = i
        irc.reply("KD: %.2f | (Avg)K/D/A:  %.1f/%.1f/%.1f | K+A/D: %f" % 
        (
        kills/deaths, kills/fullGames.count(), deaths/fullGames.count(),
        assists/fullGames.count(),(kills+assists)/deaths)
        )
        irc.reply("Heroe Mas jugado %s (%s veces)" % (self.dotaDB.heroIdtoName(mPlayed),mostPlayed[mPlayed]))
        irc.reply("The Dire: %s (%s wins %s%%), The Radiant: %s (%s wins %s%%), Wins %s, Loses %s" % 
        (
        bando["dire"],dire_win,dire_win * 100 / bando["dire"],
        bando["radiant"],radiant_win,radiant_win * 100 / bando["radiant"],
        dire_win+radiant_win,fullGames.count()-(dire_win+radiant_win))
        )
        irc.reply("Quiteo %s veces" % quits)
    pstat = wrap(pstat,["text"])

    def mpstats(self,irc,msg,args,matchNum,vanityName):
        """ use with the number of the match and steamname to get your info on the match"""
        vanityName = vanityName.lower()
        try:
            match = self.dotaDB.getMatch(matchNum)
            steam32 = self.dotaDB.vanityTo32(vanityName)
        except Dota2Error as e:
            irc.reply("Error: %s" % e.msg)
            raise
        fullHeroDamageDire = 0
        fullHeroDamageRadiant = 0
        fullHealingDire = 0
        fullHealingRadiant = 0
        fullTowerDamageDire = 0
        fullTowerDamageRadiant = 0
        heroDamagePct = 0
        towerDamagePct = 0
        healingPct = 0
        for p in match["players"]:
            if p["account_id"] == steam32:
                player = p
            if p["player_slot"] > 10:
                fullHeroDamageDire += p["hero_damage"]
                fullTowerDamageDire += p["tower_damage"]
                fullHealingDire += p["hero_healing"]
            else:
                fullHeroDamageRadiant += p["hero_damage"]
                fullTowerDamageRadiant += p["tower_damage"]
                fullHealingRadiant += p["hero_healing"]
        if player["player_slot"] > 10:
            bando = "The Dire"
            if fullHeroDamageDire != 0: heroDamagePct = player["hero_damage"] * 100 / fullHeroDamageDire
            if fullTowerDamageDire != 0: towerDamagePct = player["tower_damage"] * 100 / fullTowerDamageDire
            if fullHealingDire != 0: healingPct = player["hero_healing"] * 100 / fullHealingDire
        else:
            bando = "The Radiant"
            if fullHeroDamageRadiant != 0: heroDamagePct = player["hero_damage"] * 100 / fullHeroDamageRadiant
            if fullTowerDamageRadiant != 0: towerDamagePct = player["tower_damage"] * 100 / fullTowerDamageRadiant
            if fullHealingRadiant != 0: healingPct = player["hero_healing"] * 100 / fullHealingRadiant
        irc.reply("Match Stats #%s as %s:" %(matchNum,vanityName))
        irc.reply("Pick: %s, Lv: %s (%s)" % (self.dotaDB.heroIdtoName(player["hero_id"]),player["level"],bando))
#        if player.has_key("ability_upgrades"):
#            talents = {"3":"Q","6":"Ulti","2":"Stats","4":"W","5":"E"}
#            talentList = [ talents[str(x["ability"])[3]] for x in player["ability_upgrades"]]
#            irc.reply("Talenteo %s" % ",".join(talentList))
        irc.reply("K/D/A: %s/%s/%s, LastHits: %s, Denies: %s" % ( player["kills"], player["deaths"], player["assists"], player["last_hits"], player["denies"]))
        irc.reply("GPM: %s, XP/m: %s, G Spt %s, G Rem: %s" % (player["gold_per_min"],player["xp_per_min"],player["gold_spent"],player["gold"]))
        irc.reply("Dmg(Hero): %s (%s%%) , Dmg(Twr): %s (%s%%), Heal: %s (%s%%)" % 
        (
        player["hero_damage"],heroDamagePct,player["tower_damage"],
        towerDamagePct,player["hero_healing"],healingPct)
        )
        if match["radiant_win"]:
            if bando == "The Radiant":
                irc.reply("La Hizo!")
            else:
                irc.reply("no la hizo")
        if not match["radiant_win"]:
            if bando == "The Radiant":
                irc.reply("no la hizo")
            else:
                irc.reply("La Hizo!")
        if player["leaver_status"] == 2:
            irc.reply("Y ENCIMA QUITEO!!!")
    mpstats = wrap(mpstats,["anything","text"])

    def mstats(self,irc,msg,args,matchNum):
        """ get stats of a match """
        try:
            match = self.dotaDB.getMatch(matchNum)
        except Dota2Error as e:
            irc.reply("Error: %s" % e.msg)
            raise
        radiantList = [x for x in match["players"] if x["player_slot"] < 10]
        direList = [x for x in match["players"] if x["player_slot"] > 10]
        knownList = [x for x in match["players"] if self.dotaDB.steam32ToVanity(x["account_id"],False)]
        irc.reply("Dire: %s(%s),%s(%s),%s(%s),%s(%s),%s(%s)" % (
        self.dotaDB.steam32ToVanity(direList[0]["account_id"]),self.dotaDB.heroIdtoName(direList[0]["hero_id"]),
        self.dotaDB.steam32ToVanity(direList[1]["account_id"]),self.dotaDB.heroIdtoName(direList[1]["hero_id"]),
        self.dotaDB.steam32ToVanity(direList[2]["account_id"]),self.dotaDB.heroIdtoName(direList[2]["hero_id"]),
        self.dotaDB.steam32ToVanity(direList[3]["account_id"]),self.dotaDB.heroIdtoName(direList[3]["hero_id"]),
        self.dotaDB.steam32ToVanity(direList[4]["account_id"]),self.dotaDB.heroIdtoName(direList[4]["hero_id"])
        ))
        irc.reply("Radiant: %s(%s),%s(%s),%s(%s),%s(%s),%s(%s)" % (
        self.dotaDB.steam32ToVanity(radiantList[0]["account_id"]),self.dotaDB.heroIdtoName(radiantList[0]["hero_id"]),
        self.dotaDB.steam32ToVanity(radiantList[1]["account_id"]),self.dotaDB.heroIdtoName(radiantList[1]["hero_id"]),
        self.dotaDB.steam32ToVanity(radiantList[2]["account_id"]),self.dotaDB.heroIdtoName(radiantList[2]["hero_id"]),
        self.dotaDB.steam32ToVanity(radiantList[3]["account_id"]),self.dotaDB.heroIdtoName(radiantList[3]["hero_id"]),
        self.dotaDB.steam32ToVanity(radiantList[4]["account_id"]),self.dotaDB.heroIdtoName(radiantList[4]["hero_id"])
        ))
        reply = ""
        for x in knownList:
            reply += "%s: %s/%s/%s  "  % (self.dotaDB.steam32ToVanity(x["account_id"]),x["kills"],x["deaths"],x["assists"])
        irc.reply(reply)
    mstats = wrap(mstats,["anything"])
Class = Dota2

    

# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=09274234:
