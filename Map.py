#MineBot
#GPL and all that
# - espes

import heapq
from collections import deque
import time

from constants import *
from Utility import *

class BlockNotLoadedError(Exception):
    pass
class TimeoutError(Exception):
    pass
class Map(object):
    def __init__(self):
        
        self.chunks = {}
        
        self.adjX = [0, -1, 0, 1, 0, 0]
        self.adjY = [0, 0, -1, 0, 1, 0]
        self.adjZ = [-1, 0, 0, 0, 0, 1]
    def addChunk(self, chunk):
        self.chunks[tuple(chunk.pos)] = chunk
    def findChunk(self, position):
        x, y, z = map(ifloor, position)
        #Try assuming chunks are 16-blocks alligned
        chunkPos = (x-x%16, 0, z-z%16)
        if chunkPos in self.chunks:
            chunk = self.chunks[chunkPos]
            cx, cy, cz = chunkPos
            if cx<=x<cx+chunk.sizeX and cy<=y<cy+chunk.sizeY and cz<=z<cz+chunk.sizeZ:
                return chunk
        
        #Do a search of all chunks
        for chunkPos, chunk in self.chunks.items():
            cx, cy, cz = chunkPos
            if cx<=x<cx+chunk.sizeX and cy<=y<cy+chunk.sizeY and cz<=z<cz+chunk.sizeZ:
                return chunk
        return None
        
        
    def __getitem__(self, key):
        assert isinstance(key, Point) or isinstance(key, tuple)
        x, y, z = map(ifloor, key)
        
        if y >= 128: #World top
            return BLOCK_AIR
        elif y <= 0:
            return BLOCK_BEDROCK
        
        chunk = self.findChunk((x, y, z))
        if chunk:
            cx, cy, cz = chunk.pos
            return chunk[x-cx, y-cy, z-cz]
        
        raise BlockNotLoadedError
    def __setitem__(self, key, value):
        assert isinstance(key, Point) or isinstance(key, tuple)
        x, y, z = map(ifloor, key)
        
        chunk = self.findChunk((x, y, z))
        if chunk:
            cx, cy, cz = chunk.pos
            chunk[x-cx, y-cy, z-cz] = value
        else:
            raise BlockNotLoadedError
    def searchForBlock(self, source, targetBlock, timeout=10, maxDist=None):
        source = Point(*map(ifloor, source))
        
        startTime = time.time()
        
        visited = set([])
        visited.add(source)
        q = deque([source])
        while q:
            pos = q.popleft()
            if time.time()-startTime > timeout:
                logging.debug("last dis: %r" % (pos-source).mag())
                raise TimeoutError
            for adj in zip(self.adjX, self.adjY, self.adjZ):
                npos = pos + adj
                if maxDist is not None and npos.mag() > maxDist: continue
                if npos in visited: continue
                try:
                    if self[npos] == targetBlock:
                        return npos
                except BlockNotLoadedError:
                    continue
                
                q.append(npos)
                visited.add(npos)
        
        return None
        
    def findPath(self, start, end,
            acceptIncomplete=False,
            threshold=None, 
            destructive=False,
            blockBreakPenalty=None,
            forClient=None):
        walkableBlocks = BLOCKS_WALKABLE
        if destructive:
            walkableBlocks |= BLOCKS_BREAKABLE
        
        #Greedy BFS FTW
        #(I fail - A* slower in general case. Patches welcome)
        try:
            assert self[end] in walkableBlocks and self[end + (0, 1, 0)] in walkableBlocks
        except BlockNotLoadedError, e:
            if not acceptIncomplete:
                raise e
        assert self[start] in BLOCKS_WALKABLE
        
        adjX = self.adjX
        adjY = self.adjY
        adjZ = self.adjZ
        
        
        mapInstance = self
        class AStarNode(object):
            def __init__(self, pos):
                self.pos = pos
                self.dist = (end-self.pos).mag()
                
                try:
                    self.blockId = mapInstance[self.pos]
                    self.available = True
                except BlockNotLoadedError:
                    self.blockId = None
                    self.available = False
                
                if destructive and self.blockId in BLOCKS_BREAKABLE:
                    if blockBreakPenalty is not None:
                        self.dist += blockBreakPenalty
                    elif forClient:
                        #TODO: estimate using number of hits
                    
                        #takes about 3? game ticks to clear the blocks
                        mineTime = forClient.targetTick*3
                        mineDistance = forClient.speed*mineTime
                        self.dist += mineDistance
            def __cmp__(self, other):
                return cmp(self.dist, other.dist)
        
        pq = []
        heapq.heapify(pq)

        visited = set([])
        backTrack = {}
        found = None
        
        startNode = AStarNode(Point(*map(ifloor, start)))
        endPos = Point(*map(ifloor, end))
        
        startTime = time.time()
        
        visited.add(startNode.pos)
        heapq.heappush(pq, startNode)
        while pq and found is None:
            if time.time()-startTime > 10:
                raise TimeoutError
            
            node = heapq.heappop(pq)
            if node.pos == endPos or \
                    ((not node.available) and acceptIncomplete) or \
                    (threshold is not None and node.dist <= threshold):
                
                found = node
                break
            
            
            for adj in zip(adjX, adjY, adjZ):
                newNode = AStarNode(node.pos + adj)
                if newNode.pos in visited:
                    continue
                
                if (not newNode.available) and (not acceptIncomplete):
                    continue
                if newNode.available and (newNode.blockId not in walkableBlocks):
                    continue
                
                #Make sure the player can get through, player is 2 blocks vertically
                try:
                    if self[newNode.pos + (0, 1, 0)] not in walkableBlocks:
                        continue
                except BlockNotLoadedError:
                    pass
                
                #Make sure the block below is not a fence
                try:
                    if self[newNode.pos + (0, -1, 0)] == BLOCK_FENCE:
                        continue
                except BlockNotLoadedError:
                    pass
                
                #don't destroy blocks when things will fall on you
                try:
                    if destructive and self[newNode.pos + (0, 2, 0)] in (
                            BLOCK_GRAVEL,
                            BLOCK_SAND,
                            BLOCK_WATER,
                            BLOCK_SPRING,
                            BLOCK_LAVA,
                            BLOCK_LAVASPRING):
                        continue
                except BlockNotLoadedError:
                    pass
                
                backTrack[newNode.pos] = node
                visited.add(newNode.pos)
                heapq.heappush(pq, newNode)
        
        if found is not None:
            logging.debug("reconstruct")
            
            path = []
            cur = found
            while cur != startNode:
                path.append(cur.pos + (0.5, 0, 0.5))
                cur = backTrack[cur.pos]
            path.append(cur.pos + (0.5, 0, 0.5)) #append the start node too
            
            path.reverse()
            if acceptIncomplete:
                return path, found.available
            else:
                return path
        
        if acceptIncomplete:
            return None, False
        else:
            return None