import requests
import math
import time
import sys

MIDDLEWARE_URL = "http://localhost:8000"

def get_state():
    try:
        resp = requests.get(f"{MIDDLEWARE_URL}/state")
        if resp.status_code == 200:
            return resp.json()
    except requests.exceptions.ConnectionError:
        print("Could not connect to the Python Middleware. Is it running?")
        sys.exit(1)
    return None

def send_cmd(cmd):
    try:
        requests.post(f"{MIDDLEWARE_URL}/command", json={"command": cmd})
    except:
        pass

def generate():
    state = get_state()
    if not state or 'player_pos' not in state:
        print("No telemetry data found. Please join the Minecraft world first.")
        return
        
    px, py, pz = [int(v) for v in state['player_pos']]
    facing = state.get('facing', 'North')
    
    print(f"Player detected at [{px}, {py}, {pz}] facing {facing}.")
    print("Initiating Ominous Spherical Corridor sequence...")
    
    # We will build a ribbed, pulsating tunnel 60 blocks long.
    length = 60
    
    # Send a dramatic message to the player
    send_cmd('/title @a title {"text":"The Passage Opens","color":"dark_red"}')
    send_cmd('/playsound minecraft:ambient.basalt_deltas.mood ambient @a')
    
    for d in range(3, length + 3):
        # Determine the direction vector based on where the player is looking
        dx, dz = 0, 0
        if facing == "North": dz = -1
        elif facing == "South": dz = 1
        elif facing == "East": dx = 1
        elif facing == "West": dx = -1
        else: dz = -1 # Fallback
        
        cz = pz + d * dz
        cx = px + d * dx
        
        # The radius pulses in a wave pattern to simulate connected spheres
        # R oscillates between 5 and 9
        R = int(7 + 2 * math.cos(d * 0.45))
        
        # Iterate over the 2D cross-section of the tunnel
        for x in range(-R, R + 1):
            for y in range(-R, R + 1):
                r2 = x*x + y*y
                
                # Convert relative cross-section (x) into absolute world coordinates
                if dx == 0:
                    bx = cx + x
                    bz = cz
                else:
                    bx = cx
                    bz = cz + x
                    
                by = py + y + R - 1 # Offset Y so the floor matches player level
                
                # Check if this coordinate is inside the outer radius
                if r2 <= R*R:
                    if r2 >= (R-1)*(R-1): 
                        # We are on the Shell (Outer wall/floor/ceiling)
                        if y <= -R + 1:
                            # Floor Pattern: alternating checkerboard of dark oak and crimson
                            if (x + d) % 2 == 0:
                                block = "minecraft:stripped_dark_oak_log[axis=y]"
                            else:
                                block = "minecraft:crimson_planks"
                        else:
                            # Walls and Ceiling: mostly dark oak, with some obsidian for ominous feel
                            if (x*y*d) % 17 == 0:
                                block = "minecraft:obsidian"
                            else:
                                block = "minecraft:dark_oak_wood"
                                
                        send_cmd(f"/setblock {bx} {by} {bz} {block} replace")
                        
                    else:
                        # We are Inside the shell (Hollow space)
                        # We place air to clear any existing terrain (like stone if underground)
                        
                        # Add Soul Lanterns periodically along the walls for eerie lighting
                        if d % 6 == 0 and y == 1 and (x == R-1 or x == -(R-1)):
                            send_cmd(f"/setblock {bx} {by} {bz} minecraft:soul_lantern[hanging=false] replace")
                        else:
                            send_cmd(f"/setblock {bx} {by} {bz} minecraft:air replace")
                            
        # Print progress to the terminal
        if d % 5 == 0:
            print(f"Generated slice {d-2}/{length}...")

    send_cmd('/title @a subtitle {"text":"Do not look back.","color":"gray","italic":true}')
    print("\nGeneration complete. Check your Minecraft world.")

if __name__ == "__main__":
    generate()