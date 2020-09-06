# HIT CHECK
import pgzrun
import math
WIDTH = 800
HEIGHT = 600

player = Actor('playership1_blue.png', (700, 100))
enemy = Actor('enemyred1.png', (100, 500))

angle = enemy.angle_to(player)
distance = enemy.distance_to(player)

red = math.radians(-angle)
targetx = enemy.x + (math.cos(red)) * distance
targety = enemy.y + (math.sin(red)) * distance

def draw():
    screen.clear()
    player.draw()
    enemy.draw()
    screen.draw.line(enemy.pos, (targetx, targety), 'RED')
    screen.draw.text('ANGLE    =' + str(angle), (50, 50))
    screen.draw.text('DISTANCE =' + str(distance), (50, 100))

pgzrun.go()
