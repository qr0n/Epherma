package com.example.coordlogger;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.minecraft.block.BlockState;
import net.minecraft.registry.Registries;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.world.ServerWorld;
import net.minecraft.util.Identifier;
import net.minecraft.util.math.BlockPos;

public class BlueprintBuilder {

    public static void build(MinecraftServer server, JsonObject blueprint) {
        JsonArray originArr = blueprint.getAsJsonArray("origin");
        int ox = originArr.get(0).getAsInt();
        int oy = originArr.get(1).getAsInt();
        int oz = originArr.get(2).getAsInt();

        JsonArray dimArr = blueprint.getAsJsonArray("dimensions");
        int width  = dimArr.get(0).getAsInt();
        int height = dimArr.get(1).getAsInt();
        int depth  = dimArr.get(2).getAsInt();

        JsonObject palette = blueprint.getAsJsonObject("palette");

        // Required
        String wallBlock    = palette.get("wall").getAsString();
        String floorBlock   = palette.get("floor").getAsString();
        String ceilingBlock = palette.get("ceiling").getAsString();

        // Optional — null means "not specified"
        String pillarBlock  = palette.has("pillar")  ? palette.get("pillar").getAsString()  : null;
        String accentBlock  = palette.has("accent")  ? palette.get("accent").getAsString()  : null;
        String lightBlock   = palette.has("light")   ? palette.get("light").getAsString()   : null;
        String fillBlock    = palette.has("fill")    ? palette.get("fill").getAsString()     : null;

        server.execute(() -> {
            ServerWorld world = server.getOverworld();

            BlockState wall    = getBlock(wallBlock);
            BlockState floor   = getBlock(floorBlock);
            BlockState ceiling = getBlock(ceilingBlock);
            BlockState air     = getBlock("minecraft:air");
            BlockState pillar  = pillarBlock != null ? getBlock(pillarBlock) : null;
            BlockState accent  = accentBlock != null ? getBlock(accentBlock) : null;
            BlockState light   = lightBlock  != null ? getBlock(lightBlock)  : null;
            BlockState fill    = fillBlock   != null ? getBlock(fillBlock)   : air;

            int midY = height / 2;
            int blocksPlaced = 0;

            for (int x = 0; x < width; x++) {
                for (int y = 0; y < height; y++) {
                    for (int z = 0; z < depth; z++) {
                        boolean onMinX = x == 0;
                        boolean onMaxX = x == width - 1;
                        boolean onMinY = y == 0;
                        boolean onMaxY = y == height - 1;
                        boolean onMinZ = z == 0;
                        boolean onMaxZ = z == depth - 1;
                        boolean onShell = onMinX || onMaxX || onMinY || onMaxY || onMinZ || onMaxZ;

                        BlockState state;

                        if (!onShell) {
                            // Interior — pillar columns at the four inner corners
                            boolean isCornerX = (x == 1 || x == width - 2);
                            boolean isCornerZ = (z == 1 || z == depth - 2);
                            if (pillar != null && isCornerX && isCornerZ) {
                                state = pillar;
                            } else {
                                state = fill;
                            }
                        } else if (onMinY) {
                            state = floor;
                        } else if (onMaxY) {
                            state = ceiling;
                        } else {
                            // Wall — accent and light overlays
                            boolean isWallSurface = onMinX || onMaxX || onMinZ || onMaxZ;

                            // Light: placed on walls at mid-height, every 6 blocks along the axis
                            if (light != null && isWallSurface && y == midY) {
                                int axis = (onMinX || onMaxX) ? z : x;
                                if (axis % 6 == 3) {
                                    state = light;
                                } else {
                                    state = accentOrWall(accent, wall, x, y, z);
                                }
                            } else {
                                state = accentOrWall(accent, wall, x, y, z);
                            }
                        }

                        world.setBlockState(new BlockPos(ox + x, oy + y, oz + z), state);
                        blocksPlaced++;
                    }
                }
            }

            CoordLogger.LOGGER.info("[Ephemera] Blueprint built: {} blocks at ({}, {}, {}) dim {}x{}x{}",
                    blocksPlaced, ox, oy, oz, width, height, depth);
        });
    }

    /** Returns accent block at ~1-in-7 positions (deterministic, no RNG needed), wall otherwise. */
    private static BlockState accentOrWall(BlockState accent, BlockState wall, int x, int y, int z) {
        if (accent != null && (x * 3 + y * 7 + z * 13) % 7 == 0) {
            return accent;
        }
        return wall;
    }

    private static BlockState getBlock(String id) {
        return Registries.BLOCK.get(new Identifier(id)).getDefaultState();
    }
}
