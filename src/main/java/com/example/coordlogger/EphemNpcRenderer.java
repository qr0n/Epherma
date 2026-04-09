package com.example.coordlogger;

import net.fabricmc.api.EnvType;
import net.fabricmc.api.Environment;
import net.minecraft.client.render.entity.BipedEntityRenderer;
import net.minecraft.client.render.entity.EntityRendererFactory;
import net.minecraft.client.render.entity.model.EntityModelLayers;
import net.minecraft.client.render.entity.model.PlayerEntityModel;
import net.minecraft.util.Identifier;

@Environment(EnvType.CLIENT)
public class EphemNpcRenderer extends BipedEntityRenderer<EphemNpc, PlayerEntityModel<EphemNpc>> {

    private static final Identifier TEXTURE =
            new Identifier("minecraft", "textures/entity/player/wide/steve.png");

    public EphemNpcRenderer(EntityRendererFactory.Context ctx) {
        super(ctx, new PlayerEntityModel<>(ctx.getPart(EntityModelLayers.PLAYER), false), 0.5f);
    }

    @Override
    public Identifier getTexture(EphemNpc entity) {
        return TEXTURE;
    }
}
