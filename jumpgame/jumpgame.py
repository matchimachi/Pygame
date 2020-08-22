# JUMP GAME
import pgzrun
import random
WIDTH = 800
HEIGHT = 600

OUTSIDE = 999

# ゲームの初期化
def init():
    global player, score, objects, loopcount
    global gameover, titlemode

    player = Actor('p1_walk01.png', (100, 300))
    player.anime = 0
    player.vy = 0
    player.ground = False
    player.speed = 2
    score = 0
    loopcount = 0
    gameover = 0
    titlemode = True

    objects = []

    for i in range(int(WIDTH / 70)):
        objects.append(Actor('grass.png', (i * 70, HEIGHT - 70)))

def backward(num):
    if num < 0: return(-(70 - abs(num)))
    else: return(70 - abs(num))

def draw():
    screen.fill((180, 250, 255))
    if titlemode == True:
        screen.draw.text('J U M P  G A M E', left=250,top=250,fontsize=64,color='BLUE')
    else:
        for sp in objects:
            sp.draw()
        player.draw()
        screen.draw.text('SCORE : ' + str(score), left=250,top=250,fontsize=64,color='BLUE')

def update():
    global player, objects
    global titlemode, loopcount, gameover, score

    if titlemode == True:
        if keyboard.space: titlemode = False
        return

    if keyboard.left: player.x -= 3
    if keyboard.right: player.x += 3

    if player.ground == True:

        if keyboard.space:
            player.vy = -10
    else:

        player.vy += 0.2
        if player.vy > 10: player.vy = 10
        player.y += player.vy

    player.anime = (player.anime + 1) % 60
    if player.anime == 0:
        player.image = 'p1_walk01.png'
    if player.anime == 30:
        player.image = 'p1_walk03.png'
    
    player.ground = False

    for obj in objects:

        obj.x -= player.speed

        dx = player.x - obj.x
        dy = player.y - obj.y
        if abs(dx) < 70 and abs(dy) < 70:

            if obj.image == 'coingold.png':
                score += 1
                obj.x = OUTSIDE
                player.speed += 0.25
            else:
                if abs(dx) < abs(dy):

                    player.y += backward(dy)
                    player.vy = 0

                    if dy < 0: player.ground = True
                else:

                    player.x += backward(dx)
    for obj in objects:
        if obj.x < -16 or obj.x == OUTSIDE:
            objects.remove(obj)

    loopcount = (loopcount + 1) % 35
    if loopcount == 0:
        pos = (WIDTH+70, (random.randrange(5)+4)*70)
        if random.randrange(4) > 0:

            objects.append(Actor('grass.png',pos))
        else:
            objects.append(Actor('coingold.png',pos))

    if gameover == 0:
        if player.y > HEIGHT: gameover = 1
    else:
        gameover += 1
        if gameover > 180: init()

init()
pgzrun.go()
