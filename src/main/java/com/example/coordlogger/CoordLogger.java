package com.example.coordlogger;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.fabricmc.fabric.api.object.builder.v1.entity.FabricDefaultAttributeRegistry;
import net.minecraft.entity.EntityType;
import net.minecraft.entity.SpawnGroup;
import net.minecraft.item.ItemStack;
import net.minecraft.registry.Registries;
import net.minecraft.registry.Registry;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.util.Identifier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.URI;

public class CoordLogger implements ModInitializer {

    public static final Logger LOGGER = LoggerFactory.getLogger("coordlogger");
    private static final String SERVER_URI = "ws://localhost:8000/ws/telemetry";

    public static EntityType<EphemNpc> EPHEM_NPC;

    private EphemeraClient wsClient;
    private MinecraftServer currentServer;
    private int tickCounter = 0;
    private int reconnectTimer = 0;

    private double prevX = 0;
    private double prevY = 0;
    private double prevZ = 0;
    private float prevHealth = 0;
    private boolean firstTick = true;

    @Override
    public void onInitialize() {
        EPHEM_NPC = Registry.register(
                Registries.ENTITY_TYPE,
                new Identifier("ephemera", "npc"),
                EntityType.Builder.<EphemNpc>create(EphemNpc::new, SpawnGroup.MISC)
                        .build("ephemera.npc")
        );
        FabricDefaultAttributeRegistry.register(EPHEM_NPC, EphemNpc.createAttributes().build());

        ServerLifecycleEvents.SERVER_STARTED.register(server -> {
            this.currentServer = server;
            server.execute(() -> applyWorldSettings(server));
            connectWebSocket();
        });

        ServerLifecycleEvents.SERVER_STOPPING.register(server -> {
            if (wsClient != null && !wsClient.isClosed()) {
                wsClient.close();
            }
        });

        ServerTickEvents.END_SERVER_TICK.register(server -> {
            tickCounter++;
            if (tickCounter < 20) return;
            tickCounter = 0;

            if (wsClient == null || wsClient.isClosed()) {
                reconnectTimer++;
                if (reconnectTimer >= 5) { // Try to reconnect every 5 seconds
                    reconnectTimer = 0;
                    LOGGER.info("[Ephemera] Attempting to reconnect to orchestration server...");
                    connectWebSocket();
                }
                return;
            }

            if (!wsClient.isOpen()) return;

            server.getPlayerManager().getPlayerList()
                    .forEach(player -> wsClient.sendTelemetry(buildTelemetry(player)));
        });
    }

    private void applyWorldSettings(MinecraftServer server) {
        String[] cmds = {
            "gamerule doDaylightCycle false",
            "gamerule doWeatherCycle false",
            "gamerule doMobSpawning false",
            "gamerule doMobLoot false",
            "gamerule keepInventory true",
            "gamerule naturalRegeneration true",
            "time set 18000",
            "weather clear 999999",
        };
        for (String cmd : cmds) {
            server.getCommandManager().executeWithPrefix(server.getCommandSource(), cmd);
        }
        LOGGER.info("[Ephemera] World settings applied.");
    }

    private void connectWebSocket() {
        try {
            if (wsClient != null && !wsClient.isClosed()) {
                wsClient.close();
            }
            wsClient = new EphemeraClient(new URI(SERVER_URI), currentServer);
            wsClient.connect();
            LOGGER.info("[Ephemera] Connecting to {}", SERVER_URI);
        } catch (Exception e) {
            LOGGER.error("[Ephemera] Failed to start WebSocket client: {}", e.getMessage());
        }
    }

    private String buildTelemetry(ServerPlayerEntity player) {
        JsonObject json = new JsonObject();

        double x = player.getX();
        double y = player.getY();
        double z = player.getZ();
        float health = player.getHealth();

        if (firstTick) {
            prevX = x;
            prevY = y;
            prevZ = z;
            prevHealth = health;
            firstTick = false;
        }

        double dx = x - prevX;
        double dy = y - prevY;
        double dz = z - prevZ;
        double speed = Math.sqrt(dx * dx + dy * dy + dz * dz);
        float healthDelta = health - prevHealth;

        String action = "idle";
        ItemStack mainHand = player.getMainHandStack();
        String heldItem = "";
        if (!mainHand.isEmpty()) {
            heldItem = Registries.ITEM.getId(mainHand.getItem()).toString();
        }

        if (healthDelta < 0) {
            action = "taking_damage";
        } else if (heldItem.contains("_sword")) {
            action = "in_combat";
        } else if (heldItem.contains("_pickaxe") || heldItem.contains("_axe") || heldItem.contains("_shovel")) {
            action = "mining";
        } else if (speed > 4.5) {
            // speed is blocks/second (measured over 20 ticks); sprinting ~5.6, walking ~4.3
            action = "sprinting";
        } else if (speed > 0.5) {
            action = "walking";
        }

        prevX = x;
        prevY = y;
        prevZ = z;
        prevHealth = health;

        JsonArray pos = new JsonArray();
        pos.add(x);
        pos.add(y);
        pos.add(z);
        json.add("player_pos", pos);

        json.addProperty("player_name", player.getName().getString());
        json.addProperty("facing", yawToDirection(player.getYaw()));
        json.addProperty("health", health);
        json.addProperty("health_delta", healthDelta);
        json.addProperty("speed", speed);
        json.addProperty("action", action);

        // Non-empty main inventory slots as namespaced item IDs
        JsonArray inventory = new JsonArray();
        for (ItemStack stack : player.getInventory().main) {
            if (!stack.isEmpty()) {
                inventory.add(Registries.ITEM.getId(stack.getItem()).toString());
            }
        }
        json.add("inventory", inventory);
        json.addProperty("world_seed", currentServer.getOverworld().getSeed());

        return json.toString();
    }

    /** Convert Minecraft yaw (degrees, 0 = South, clockwise) to a compass direction. */
    private String yawToDirection(float yaw) {
        yaw = ((yaw % 360) + 360) % 360;
        if (yaw < 45 || yaw >= 315) return "South";
        if (yaw < 135)              return "West";
        if (yaw < 225)              return "North";
        return                             "East";
    }
}
