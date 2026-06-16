public class EarSkinCompat {
    public static gs renderingPlayer;
    public static float renderingTickDelta;

    public static void setRenderingPlayer(gs player, float tickDelta) {
        renderingPlayer = player;
        renderingTickDelta = tickDelta;
        renderFrame++;
    }

    public static net.minecraft.move.ModelRotationRenderer slimLeftArm;
    public static net.minecraft.move.ModelRotationRenderer slimRightArm;
    public static net.minecraft.move.ModelRotationRenderer fatLeftArm;
    public static net.minecraft.move.ModelRotationRenderer fatRightArm;

    public static net.minecraft.move.ModelPlayer mainModel;
    public static net.minecraft.move.ModelPlayer modelCape;
    public static int renderFrame = 0;
    public static int aetherCapeFrame = -2;
    public static net.minecraft.move.ModelPlayer modelEnergyShield;
    public static net.minecraft.move.ModelPlayer modelMisc;
    public static net.minecraft.move.ModelPlayer modelArmorChestplate;
    public static net.minecraft.move.ModelPlayer modelArmor;

    public static void setForceTextureHeight(boolean val) {
        try {
            java.lang.reflect.Field f = Class.forName("com_unascribed_ears_Ears").getDeclaredField("forceTextureHeight");
            f.setAccessible(true);
            f.setBoolean(null, val);
        } catch (Throwable t) {
            // Ignore
        }
    }

    public static void handleSlimArm(net.minecraft.move.ModelPlayer mp, gs player) {
        try {
            if (slimLeftArm == null) {
                // In case init wasn't called yet
                init(mp, 0.0f);
            }
            boolean isSlim = player.l != null && com.unascribed.ears.legacy.LegacyHelper.isSlimArms(player.l);
            if (isSlim) {
                mp.e = slimLeftArm;
                mp.d = slimRightArm;
                ((fh) mp).e = slimLeftArm;
                ((fh) mp).d = slimRightArm;
            } else {
                mp.e = fatLeftArm;
                mp.d = fatRightArm;
                ((fh) mp).e = fatLeftArm;
                ((fh) mp).d = fatRightArm;
            }

            // Also keep Ears mod static fields synchronized!
            try {
                Class<?> earsCls = Class.forName("com_unascribed_ears_Ears");
                earsCls.getField("slimLeftArm").set(null, slimLeftArm);
                earsCls.getField("slimRightArm").set(null, slimRightArm);
                earsCls.getField("fatLeftArm").set(null, fatLeftArm);
                earsCls.getField("fatRightArm").set(null, fatRightArm);
            } catch (Throwable t) {
                // Ignore
            }

            // Dynamic cape visibility check
            if (mp.i != null) {
                boolean hasEarsCape = false;
                try {
                    String skinUrl = com.unascribed.ears.legacy.LegacyHelper.getSkinUrl(player.l);
                    com.unascribed.ears.api.features.EarsFeatures features =
                        (com.unascribed.ears.api.features.EarsFeatures)
                        ((java.util.Map) Class.forName("com_unascribed_ears_Ears").getField("earsSkinFeatures").get(null)).get(skinUrl);
                    if (features != null && features.capeEnabled) {
                        hasEarsCape = true;
                    }
                } catch (Throwable t) {
                    // Ignore
                }
                boolean hasAetherCape = (aetherCapeFrame >= renderFrame - 1);
                boolean hide = mp.isCrawl || mp.isClimb || mp.isSwim || mp.isDive || mp.isCrawlClimb || hasAetherCape;
                mp.i.h = !hasEarsCape && !hide;
            }
        } catch (Throwable t) {
            // Ignore
        }
    }

    public static void init(net.minecraft.move.ModelPlayer mp, float scale) {
        // Synchronize all shadowed fields from ModelPlayer to ModelBiped (fh)
        // so that Ears mod retrieves the animated Smart Moving model parts.
        ((fh) mp).a = mp.a;
        ((fh) mp).b = mp.b;
        ((fh) mp).c = mp.c;
        ((fh) mp).d = mp.d;
        ((fh) mp).e = mp.e;
        ((fh) mp).f = mp.f;
        ((fh) mp).g = mp.g;
        ((fh) mp).h = mp.h;
        ((fh) mp).i = mp.i;

        if (scale > 0.0f) {
            // This is an armor / shield / misc accessory model.
            if (scale == 1.25f) {
                modelEnergyShield = mp;
            } else if (scale == 0.6f) {
                modelMisc = mp;
            } else if (scale == 1.0f) {
                modelArmorChestplate = mp;
            } else if (scale == 0.5f) {
                modelArmor = mp;
            }
            // Disable cape rendering to prevent the static duplicate cape inside the body.
            if (mp.i != null) {
                mp.i.h = false;
            }
            return;
        }

        // scale == 0.0f: Main player model or Aether modelCape
        if (mainModel == null) {
            mainModel = mp;
        } else {
            modelCape = mp;
        }

        if (fatLeftArm == null) {
            fatLeftArm = mp.e;
            fatRightArm = mp.d;

            slimLeftArm = new net.minecraft.move.ModelRotationRenderer(32, 48, mp.c);
            slimLeftArm.a(-1.0f, -2.0f, -2.0f, 3, 12, 4, 0.0f);
            slimLeftArm.a(5.0f, 2.5f, 0.0f);

            slimRightArm = new net.minecraft.move.ModelRotationRenderer(40, 16, mp.c);
            slimRightArm.a(-2.0f, -2.0f, -2.0f, 3, 12, 4, 0.0f);
            slimRightArm.a(-5.0f, 2.5f, 0.0f);
        }
    }

    public static void syncBeforeRender(net.minecraft.move.ModelPlayer mp) {
        if (mp == null || mainModel == null) return;
        if (mp == mainModel) {
            clearEarsBoundTexture();
        }
        if (mp != mainModel) {
            boolean isAccessory = (mp == modelEnergyShield || mp == modelMisc || mp == modelCape);
            if (isAccessory) {
                boolean hide = mainModel.isCrawl || mainModel.isClimb || mainModel.isSwim || mainModel.isDive || mainModel.isCrawlClimb;
                if (hide) {
                    mp.a.h = false;
                    mp.b.h = false;
                    mp.c.h = false;
                    mp.d.h = false;
                    mp.e.h = false;
                    mp.f.h = false;
                    mp.g.h = false;
                    if (mp.i != null) mp.i.h = false;
                    return;
                }
            }
            syncModelRotations(mainModel, mp);
        }
    }

    private static java.lang.reflect.Field smrField;
    static {
        try {
            smrField = net.minecraft.move.ModelPlayer.class.getDeclaredField("smr");
            smrField.setAccessible(true);
        } catch (Throwable t) {
            // Ignore
        }
    }

    public static void syncModelRotations(net.minecraft.move.ModelPlayer main, net.minecraft.move.ModelPlayer other) {
        if (main == null || other == null) return;
        boolean isArmor = false;
        if (smrField != null) {
            try {
                net.minecraft.move.SmartMovingRender smr = (net.minecraft.move.SmartMovingRender) smrField.get(other);
                if (smr != null) {
                    isArmor = (other == smr.modelArmorChestplate || other == smr.modelArmor);
                }
            } catch (Throwable t) {
                // Ignore
            }
        }
        boolean copyShowModel = !isArmor;
        copyRotation(main.a, other.a, copyShowModel); // head
        copyRotation(main.b, other.b, copyShowModel); // headwear
        copyRotation(main.c, other.c, copyShowModel); // body
        copyRotation(main.d, other.d, copyShowModel); // rightArm
        copyRotation(main.e, other.e, copyShowModel); // leftArm
        copyRotation(main.f, other.f, copyShowModel); // rightLeg
        copyRotation(main.g, other.g, copyShowModel); // leftLeg
    }

    private static void copyRotation(net.minecraft.move.ModelRotationRenderer src, net.minecraft.move.ModelRotationRenderer dest, boolean copyShowModel) {
        if (src == null || dest == null) return;
        dest.d = src.d; // rotateAngleX
        dest.e = src.e; // rotateAngleY
        dest.f = src.f; // rotateAngleZ
        dest.a = src.a; // rotationPointX
        dest.b = src.b; // rotationPointY
        dest.c = src.c; // rotationPointZ
        dest.g = src.g; // mirror
        if (copyShowModel) {
            dest.h = src.h; // showModel
        }
        dest.ignoreBase = src.ignoreBase;
        dest.ignoreBaseRotationX = src.ignoreBaseRotationX;
        dest.ignoreBaseRotationY = src.ignoreBaseRotationY;
    }

    private static boolean earsModelPatched = false;
    private static fh earsMyModel;

    private static Object getFieldValueRecursive(Object obj, String fieldName) {
        if (obj == null) return null;
        Class<?> cls = obj.getClass();
        while (cls != null) {
            try {
                java.lang.reflect.Field f = cls.getDeclaredField(fieldName);
                f.setAccessible(true);
                return f.get(obj);
            } catch (Throwable t) {
                cls = cls.getSuperclass();
            }
        }
        return null;
    }

    public static fh getEarsMyModel() {
        if (earsMyModel == null) {
            try {
                java.lang.reflect.Field f = Class.forName("com_unascribed_ears_Ears").getDeclaredField("myModel");
                f.setAccessible(true);
                earsMyModel = (fh) f.get(null);
            } catch (Throwable t) {
                // Ignore
            }
        }
        return earsMyModel;
    }

    public static void syncEarsModel() {
        if (!earsModelPatched) {
            try {
                fh myModel = getEarsMyModel();
                if (myModel != null) {
                    if (!(myModel.i instanceof net.minecraft.move.ModelCapeRenderer)) {
                        if (mainModel != null && mainModel.i != null) {
                            myModel.i = mainModel.i;
                            earsModelPatched = true;
                        }
                    }
                }
            } catch (Throwable t) {
                // Ignore
            }
        }
    }

    public static void beforeRenderCape(Object mp) {
        syncEarsModel();
        try {
            fh model = (fh) mp;
            if (model != null && model.i instanceof net.minecraft.move.ModelCapeRenderer) {
                gs player = renderingPlayer;
                float tickDelta = renderingTickDelta;

                if (player == null) {
                    Class<?> earsClass = Class.forName("com_unascribed_ears_Ears");
                    java.lang.reflect.Field instField = earsClass.getDeclaredField("INST");
                    instField.setAccessible(true);
                    Object inst = instField.get(null);
                    if (inst != null) {
                        java.lang.reflect.Field delegateField = earsClass.getDeclaredField("delegate");
                        delegateField.setAccessible(true);
                        Object delegate = delegateField.get(inst);
                        if (delegate != null) {
                            player = (gs) getFieldValueRecursive(delegate, "peer");
                        }
                        java.lang.reflect.Field tickDeltaField = earsClass.getDeclaredField("tickDelta");
                        tickDeltaField.setAccessible(true);
                        tickDelta = tickDeltaField.getFloat(inst);
                    }
                }

                if (player != null) {
                    ((net.minecraft.move.ModelCapeRenderer) model.i).setCurrent(player, tickDelta);
                }
            }
        } catch (Throwable t) {
            // Ignore
        }

        boolean shouldPop = (mp == mainModel || (earsModelPatched && mp == getEarsMyModel()));
        if (shouldPop) {
            org.lwjgl.opengl.GL11.glPopMatrix();
        }
    }

    public static void afterRenderCape(Object mp) {
        boolean shouldPop = (mp == mainModel || (earsModelPatched && mp == getEarsMyModel()));
        if (shouldPop) {
            org.lwjgl.opengl.GL11.glPushMatrix();
        }
    }

    public static void setupAetherCape(Object renderPlayerAether) {
        try {
            if (renderPlayerAether != null) {
                java.lang.reflect.Field renderField = renderPlayerAether.getClass().getField("render");
                renderField.setAccessible(true);
                Object render = renderField.get(renderPlayerAether);
                if (render != null) {
                    java.lang.reflect.Field smModelCapeField = render.getClass().getField("modelCape");
                    smModelCapeField.setAccessible(true);
                    Object smModelCape = smModelCapeField.get(render);
                    if (smModelCape != null) {
                        java.lang.reflect.Field iField = smModelCape.getClass().getField("i");
                        iField.setAccessible(true);
                        Object mcr = iField.get(smModelCape);
                        
                        Class<?> rpaClass = Class.forName("RenderPlayerAether");
                        java.lang.reflect.Field rpaModelCapeField = rpaClass.getDeclaredField("modelCape");
                        rpaModelCapeField.setAccessible(true);
                        Object rpaModelCape = rpaModelCapeField.get(renderPlayerAether);
                        
                        if (rpaModelCape != null && mcr != null) {
                            java.lang.reflect.Field fhIField = rpaModelCape.getClass().getField("i");
                            fhIField.setAccessible(true);
                            fhIField.set(rpaModelCape, mcr);
                        }
                    }
                }
            }
        } catch (Throwable t) {
            // Ignore
        }
    }

    public static void adjustCape(Object capeRenderer, Object player) {
        try {
            gs p = null;
            if (player instanceof gs) {
                p = (gs) player;
            } else if (renderingPlayer != null) {
                p = renderingPlayer;
            }
            
            if (p != null) {
                // Aether path uses modelCape MCR; vanilla path uses a separate ModelBiped MCR
                // Vanilla: 3 voxels back (+0.1875f), Aether: 2 voxels back (+0.125f)
                boolean isAether = (modelCape != null && modelCape.i == capeRenderer);
                if (isAether) aetherCapeFrame = renderFrame;
                org.lwjgl.opengl.GL11.glTranslatef(0.0f, 0.0f, isAether ? 0.125f : 0.1875f);

                boolean isSneaking = p.t();
                if (isSneaking) {
                    org.lwjgl.opengl.GL11.glRotatef(-30.0f, 1.0f, 0.0f, 0.0f);
                }
            }
        } catch (Throwable t) {
            // Ignore
        }
    }

    public static int getLeftArmX(float scale) {
        return scale > 0.0f ? 40 : 32;
    }

    public static int getLeftArmY(float scale) {
        return scale > 0.0f ? 16 : 48;
    }

    public static int getLeftLegX(float scale) {
        return scale > 0.0f ? 0 : 16;
    }

    public static int getLeftLegY(float scale) {
        return scale > 0.0f ? 16 : 48;
    }

    public static boolean getLeftLimbMirror(float scale) {
        return scale > 0.0f;
    }

    public static void setForceHeightConditional(boolean val, float scale) {
        if (scale == 0.0f) {
            setForceTextureHeight(val);
        }
    }

    /**
     * Safe wrapper that calls ModelCapeRenderer.setCurrent on ALL ModelPlayer fields
     * found on the given SmartMovingRender instance (via reflection), ensuring that
     * accessory models (modelCape, modelEnergyShield, modelMisc) also get the player
     * reference before rendering, preventing NPE in ModelCapeRenderer.preTransform.
     */
    public static void setCurrentSafe(net.minecraft.move.ModelPlayer mp, gs player, float tickDelta) {
        try {
            if (mp != null && mp.i != null) {
                mp.i.setCurrent(player, tickDelta);
            }
        } catch (Throwable t) {
            // Ignore
        }
    }

    /**
     * Called at the start of SmartMovingRender.renderPlayer (via bytecode injection).
     * Calls setCurrent on ALL ModelCapeRenderer instances found on the SmartMovingRender
     * and on its IRenderPlayer (RenderPlayerAether) so vanilla Aether model cape renderers
     * also get the player reference and don't NPE in preTransform.
     */
    public static void setAllCapesCurrent(Object smr, net.minecraft.move.ModelPlayer mbm, gs player, float tickDelta) {
        // 1. Set on modelBipedMain (the SmartMovingRender's main model)
        setCurrentSafe(mbm, player, tickDelta);

        // 2. Set on all other ModelPlayer fields of SmartMovingRender
        if (smr != null) {
            try {
                for (java.lang.reflect.Field f : smr.getClass().getFields()) {
                    if (net.minecraft.move.ModelPlayer.class.isAssignableFrom(f.getType())) {
                        try {
                            net.minecraft.move.ModelPlayer m = (net.minecraft.move.ModelPlayer) f.get(smr);
                            if (m != null && m != mbm && m.i != null) {
                                m.i.setCurrent(player, tickDelta);
                            }
                        } catch (Throwable t2) { /* ignore */ }
                    }
                }
            } catch (Throwable t) { /* ignore */ }
        }

        // 3. Set on the IRenderPlayer's modelCape (the vanilla Aether fh model)
        // The vanilla Aether RenderPlayerAether.modelCape is a plain fh (ModelBiped)
        // which also has a ModelCapeRenderer as its .i field.
        if (smr != null) {
            try {
                java.lang.reflect.Field irpField = smr.getClass().getDeclaredField("irp");
                irpField.setAccessible(true);
                Object irp = irpField.get(smr);
                if (irp != null) {
                    // Try each field of the IRenderPlayer that is an fh (ModelBiped)
                    for (java.lang.reflect.Field f : irp.getClass().getDeclaredFields()) {
                        try {
                            f.setAccessible(true);
                            Object val = f.get(irp);
                            if (val instanceof fh) {
                                fh model = (fh) val;
                                if (model.i instanceof net.minecraft.move.ModelCapeRenderer) {
                                    ((net.minecraft.move.ModelCapeRenderer) model.i).setCurrent(player, tickDelta);
                                }
                            }
                        } catch (Throwable t2) { /* ignore */ }
                    }
                    // Also try superclass fields
                    for (java.lang.reflect.Field f : irp.getClass().getSuperclass().getDeclaredFields()) {
                        try {
                            f.setAccessible(true);
                            Object val = f.get(irp);
                            if (val instanceof fh) {
                                fh model = (fh) val;
                                if (model.i instanceof net.minecraft.move.ModelCapeRenderer) {
                                    ((net.minecraft.move.ModelCapeRenderer) model.i).setCurrent(player, tickDelta);
                                }
                            }
                        } catch (Throwable t2) { /* ignore */ }
                    }
                }
            } catch (Throwable t) { /* ignore */ }
        }
    }

    public static void restorePlayerSkin(Object renderer, Object player) {
        clearEarsBoundTexture();
        java.io.File logFile = new java.io.File("D:\\Games\\Minecraft\\instances\\Mango Pack Beta 1.7.3 (Volume 2)\\smartmoving\\ears_debug.txt");
        java.io.PrintWriter pw = null;
        try {
            pw = new java.io.PrintWriter(new java.io.FileWriter(logFile, true));
            pw.println("restorePlayerSkin called: renderer=" + renderer + ", player=" + player);
            if (renderer != null && player != null) {
                Class<?> playerClass = Class.forName("gs");
                if (playerClass.isInstance(player)) {
                    String skinUrl = (String) getFieldValueRecursive(player, "bA");
                    pw.println("  skinUrl (bA)=" + skinUrl);
                    
                    String fallback = null;
                    Class<?> pCls = player.getClass();
                    while (pCls != null) {
                        try {
                            java.lang.reflect.Method qMethod = pCls.getDeclaredMethod("q_");
                            qMethod.setAccessible(true);
                            fallback = (String) qMethod.invoke(player);
                            pw.println("  fallback (q_)=" + fallback);
                            break;
                        } catch (Throwable t) {
                            pCls = pCls.getSuperclass();
                        }
                    }
                    
                    Class<?> rCls = renderer.getClass();
                    boolean invoked = false;
                    while (rCls != null) {
                        try {
                            java.lang.reflect.Method m = rCls.getDeclaredMethod("a", String.class, String.class);
                            m.setAccessible(true);
                            m.invoke(renderer, skinUrl, fallback);
                            invoked = true;
                            pw.println("  Successfully invoked method 'a' on class " + rCls.getName());
                            break;
                        } catch (Throwable t) {
                            pw.println("  Failed method 'a' on class " + rCls.getName() + ": " + t.toString());
                            rCls = rCls.getSuperclass();
                        }
                    }
                    if (!invoked) {
                        pw.println("  WARNING: method 'a' was never invoked!");
                    }
                } else {
                    pw.println("  player is not an instance of gs! class=" + player.getClass().getName());
                }
            }
        } catch (Throwable t) {
            if (pw != null) {
                pw.println("Global exception: " + t.toString());
                t.printStackTrace(pw);
            }
        } finally {
            if (pw != null) {
                pw.close();
            }
        }
    }

    private static java.lang.reflect.Field earsBoundField;
    private static Object earsDelegate;
    private static boolean earsChecked = false;

    public static void clearEarsBoundTexture() {
        try {
            if (!earsChecked) {
                earsChecked = true;
                Class<?> earsClass = Class.forName("com_unascribed_ears_Ears");
                java.lang.reflect.Field instField = earsClass.getDeclaredField("INST");
                instField.setAccessible(true);
                Object inst = instField.get(null);
                if (inst != null) {
                    java.lang.reflect.Field delegateField = earsClass.getDeclaredField("delegate");
                    delegateField.setAccessible(true);
                    earsDelegate = delegateField.get(inst);
                    if (earsDelegate != null) {
                        Class<?> c = earsDelegate.getClass();
                        while (c != null && earsBoundField == null) {
                            try {
                                earsBoundField = c.getDeclaredField("bound");
                            } catch (NoSuchFieldException e) {
                                c = c.getSuperclass();
                            }
                        }
                        if (earsBoundField != null) {
                            earsBoundField.setAccessible(true);
                        }
                    }
                }
            }
            if (earsBoundField != null && earsDelegate != null) {
                earsBoundField.set(earsDelegate, null);
            }
        } catch (Throwable t) {
            // Ignore
        }
    }
}
