package com.example.coordlogger;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import net.minecraft.server.MinecraftServer;
import org.java_websocket.client.WebSocketClient;
import org.java_websocket.handshake.ServerHandshake;

import java.net.URI;

public class EphemeraClient extends WebSocketClient {

    private final MinecraftServer server;

    public EphemeraClient(URI serverUri, MinecraftServer server) {
        super(serverUri);
        this.server = server;
    }

    @Override
    public void onOpen(ServerHandshake handshake) {
        CoordLogger.LOGGER.info("[Ephemera] Connected to orchestration server");
    }

    @Override
    public void onMessage(String message) {
        try {
            JsonObject json = JsonParser.parseString(message).getAsJsonObject();

            if (json.has("action") && json.get("action").getAsString().equals("build_blueprint")) {
                // Structure B — Procedural Blueprint
                JsonObject blueprint = json.getAsJsonObject("blueprint");
                CoordLogger.LOGGER.info("[Ephemera] Received blueprint: type={}", blueprint.get("type").getAsString());
                BlueprintBuilder.build(server, blueprint);
            } else {
                // Structure A — Legacy raw command
                String command = json.get("command").getAsString();
                CoordLogger.LOGGER.info("[Ephemera] Received command: {}", command);
                server.execute(() -> {
                    try {
                        server.getCommandManager().executeWithPrefix(server.getCommandSource(), command);
                    } catch (Exception ex) {
                        CoordLogger.LOGGER.error("[Ephemera] Command execution failed: {}", ex.getMessage());
                    }
                });
            }
        } catch (Exception e) {
            CoordLogger.LOGGER.error("[Ephemera] Failed to handle incoming message: {}", e.getMessage());
        }
    }

    @Override
    public void onClose(int code, String reason, boolean remote) {
        CoordLogger.LOGGER.info("[Ephemera] Disconnected (code={}, reason={})", code, reason);
    }

    @Override
    public void onError(Exception ex) {
        CoordLogger.LOGGER.error("[Ephemera] WebSocket error: {}", ex.getMessage());
    }

    /** Thread-safe send — silently drops if not connected. */
    public void sendTelemetry(String json) {
        if (isOpen()) {
            send(json);
        }
    }
}
