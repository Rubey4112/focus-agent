# The BSP's showcase app: LCD, WS2812 bar, I2S audio and the power-off hold,
# all at once. Read display/main.c's header for the build and asset steps.
add_executable(ogvegas_display display/main.c display/ogvegas_assets.c)
target_link_libraries(ogvegas_display fwog_display_bsp)
fwog_display_app(ogvegas_display
    VERSION 001
    DESCRIPTION "OG Vegas startup image, ten-second audio replay, and animated red LED comet")

add_executable(ogvegas_main main/main.c)
target_link_libraries(ogvegas_main fwog_main_bsp)
# No argument, so this carries ogvegas_display -- the app in this folder.
fwog_embed_display_image(ogvegas_main)
fwog_main_app(ogvegas_main
    VERSION 001
    DESCRIPTION "OG Vegas main app carrying the matching display firmware")
