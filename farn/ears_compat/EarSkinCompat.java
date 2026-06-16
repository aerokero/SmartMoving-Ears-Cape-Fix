package farn.ears_compat;

public class EarSkinCompat {
    public static ps slimLeftArm;
    public static ps slimRightArm;
    public static ps fatLeftArm;
    public static ps fatRightArm;

    public static void setForceTextureHeight(boolean val) {
        try {
            java.lang.reflect.Field f = Class.forName("com_unascribed_ears_Ears").getDeclaredField("forceTextureHeight");
            f.setAccessible(true);
            f.setBoolean(null, val);
        } catch (Throwable t) {
            // Ignore
        }
    }

    public static void handleSlimArm(fh biped, boolean isSlim) {
        if (isSlim && ModLoader.getMinecraftInstance().h.l != null && com.unascribed.ears.legacy.LegacyHelper.isSlimArms(ModLoader.getMinecraftInstance().h.l)) {
            biped.e = slimLeftArm;
            biped.d = slimRightArm;
        } else {
            biped.e = fatLeftArm;
            biped.d = fatRightArm;
        }
    }

    public static void init(fh biped) {
        fatLeftArm = biped.e;
        fatRightArm = biped.d;

        slimLeftArm = new ps(32, 48);
        slimLeftArm.a(-1.0f, -2.0f, -2.0f, 3, 12, 4, 0.0f);
        slimLeftArm.a(5.0f, 2.5f, 0.0f);

        slimRightArm = new ps(40, 16);
        slimRightArm.a(-2.0f, -2.0f, -2.0f, 3, 12, 4, 0.0f);
        slimRightArm.a(-5.0f, 2.5f, 0.0f);
    }
}
