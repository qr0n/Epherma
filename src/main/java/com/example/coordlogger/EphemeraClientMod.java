package com.example.coordlogger;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.rendering.v1.EntityRendererRegistry;

public class EphemeraClientMod implements ClientModInitializer {

    @Override
    public void onInitializeClient() {
        EntityRendererRegistry.register(CoordLogger.EPHEM_NPC, EphemNpcRenderer::new);
    }
}
