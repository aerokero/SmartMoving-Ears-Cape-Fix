public class SmartMovingFeatures {
    public static float fovTarget = 0.0f;
    public static float fovCurrent = 0.0f;

    public static long lastWPressTime = 0L;
    public static boolean lastWPressed = false;
    public static boolean doubleTapSprintArmed = false;

    public static void updateFOV(Object minecraft) {
        try {
            boolean isSprinting = getSprinting(minecraft);
            fovTarget = isSprinting ? 92.0f : 90.0f;

            if (Math.abs(fovCurrent - fovTarget) > 0.1f) {
                fovCurrent += (fovTarget - fovCurrent) * 0.1f;
            } else {
                fovCurrent = fovTarget;
            }

            setFOV(minecraft, fovCurrent);
        } catch (Throwable t) {
            // Ignore
        }
    }

    public static void detectDoubleTapSprint(Object entityPlayer) {
        try {
            boolean wPressed = isWKeyPressed();
            long currentTime = System.currentTimeMillis();

            if (wPressed && !lastWPressed) {
                if (currentTime - lastWPressTime < 200L) {
                    doubleTapSprintArmed = true;
                    try {
                        java.lang.reflect.Field isSprinting = entityPlayer.getClass().getDeclaredField("isSprinting");
                        isSprinting.setAccessible(true);
                        isSprinting.setBoolean(entityPlayer, true);
                    } catch (Throwable t1) {
                        java.lang.reflect.Field sprinting = entityPlayer.getClass().getDeclaredField("sprinting");
                        sprinting.setAccessible(true);
                        sprinting.setBoolean(entityPlayer, true);
                    }
                }
                lastWPressTime = currentTime;
            }

            lastWPressed = wPressed;

            if (!wPressed) {
                doubleTapSprintArmed = false;
            }
        } catch (Throwable t) {
            // Ignore
        }
    }

    public static void grabOnInteract(Object entityPlayer) {
        try {
            boolean interactPressed = isInteractKeyPressed();
            boolean handsEmpty = checkHandsEmpty(entityPlayer);

            if (interactPressed && handsEmpty) {
                Object smartMoving = getSmartMoving(entityPlayer);
                if (smartMoving != null) {
                    callGrab(smartMoving);
                }
            }
        } catch (Throwable t) {
            // Ignore
        }
    }

    private static boolean getSprinting(Object minecraft) {
        try {
            Class<?> entityPlayerClass = Class.forName("tk");
            java.lang.reflect.Field thePlayerField = null;
            try {
                thePlayerField = minecraft.getClass().getDeclaredField("t");
            } catch (Throwable t1) {
                thePlayerField = minecraft.getClass().getDeclaredField("h");
            }
            thePlayerField.setAccessible(true);
            Object thePlayer = thePlayerField.get(minecraft);

            if (thePlayer != null) {
                java.lang.reflect.Field sprintField = null;
                try {
                    sprintField = entityPlayerClass.getDeclaredField("isSprinting");
                } catch (Throwable t) {
                    sprintField = entityPlayerClass.getDeclaredField("sprinting");
                }
                sprintField.setAccessible(true);
                return sprintField.getBoolean(thePlayer);
            }
        } catch (Throwable t) {
            // Ignore
        }
        return false;
    }

    private static void setFOV(Object minecraft, float fov) {
        try {
            Class<?> settingsClass = Class.forName("ug");
            java.lang.reflect.Field gameSettingsField = minecraft.getClass().getDeclaredField("g");
            gameSettingsField.setAccessible(true);
            Object gameSettings = gameSettingsField.get(minecraft);

            java.lang.reflect.Field fovField = settingsClass.getDeclaredField("e");
            fovField.setAccessible(true);
            fovField.setFloat(gameSettings, fov);
        } catch (Throwable t) {
            // Ignore
        }
    }

    private static boolean isWKeyPressed() {
        try {
            Class<?> keyboardClass = Class.forName("rb");
            java.lang.reflect.Method isKeyDownMethod = keyboardClass.getDeclaredMethod("a", int.class);
            isKeyDownMethod.setAccessible(true);
            return (boolean) isKeyDownMethod.invoke(null, 17); // 17 = W key
        } catch (Throwable t) {
            return false;
        }
    }

    private static boolean isInteractKeyPressed() {
        try {
            Class<?> keyboardClass = Class.forName("rb");
            java.lang.reflect.Method isKeyDownMethod = keyboardClass.getDeclaredMethod("a", int.class);
            isKeyDownMethod.setAccessible(true);
            return (boolean) isKeyDownMethod.invoke(null, 18); // 18 = right-click equivalent (place block)
        } catch (Throwable t) {
            return false;
        }
    }

    private static boolean checkHandsEmpty(Object entityPlayer) {
        try {
            java.lang.reflect.Field inventoryField = entityPlayer.getClass().getDeclaredField("l");
            inventoryField.setAccessible(true);
            Object inventory = inventoryField.get(entityPlayer);

            java.lang.reflect.Field mainHandField = inventory.getClass().getDeclaredField("c");
            mainHandField.setAccessible(true);
            Object mainHand = mainHandField.get(inventory);

            return mainHand == null;
        } catch (Throwable t) {
            return false;
        }
    }

    private static Object getSmartMoving(Object entityPlayer) {
        try {
            if (entityPlayer.getClass().getName().contains("move")) {
                java.lang.reflect.Field movingField = entityPlayer.getClass().getDeclaredField("moving");
                movingField.setAccessible(true);
                return movingField.get(entityPlayer);
            }
        } catch (Throwable t) {
            // Ignore
        }
        return null;
    }

    private static void callGrab(Object smartMoving) {
        try {
            java.lang.reflect.Method grabMethod = null;
            try {
                grabMethod = smartMoving.getClass().getDeclaredMethod("grab");
            } catch (Throwable t1) {
                grabMethod = smartMoving.getClass().getDeclaredMethod("doGrab");
            }
            grabMethod.setAccessible(true);
            grabMethod.invoke(smartMoving);
        } catch (Throwable t) {
            // Ignore
        }
    }
}
