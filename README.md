If you want to contribute see [Contributing](https://github.com/MiepHD/cuscon/edit/master/README.md#contributing)

![icon_with_name](http://miep-hd.froxot.com/cuscon/res/icon_with_name.png)

This icon pack brings variety and dynamism to your Home screen with over 5000 icons. Without a background, each icon looks unique and breaks the constant pattern of the grid. All icons have a black border which allows them to fit on most backgrounds. The color palette is retained and integrated into the icon. This makes the icons easy to recognize. Cuscon also brings a natural consistency to the size of the icons. All icons have the same spacing, resulting in a standard size without the need to mask icons. Unlike many other icon packs, Cuscon's philosophy supports the creation of icons for games and other complex icons. Therefore, it is possible to have Cuscon fully applied without annoying unedited icons that don't fit the theme. Since Cuscon is open source, anyone can contribute icons and other changes on Github. Cuscon supports most launchers such as Apex, Nova, Smart, Kiss, Lawnchair and others. You can request icons that have not yet been added to the application. Most calendars can update based on the date if the correct launcher is used.

# Download

[<img src="https://fdroid.gitlab.io/artwork/badge/get-it-on.png"
     alt="Get it on F-Droid"
     height="80">](https://f-droid.org/packages/com.froxot.cuscon.foss/)
[<img src="https://play.google.com/intl/en_us/badges/images/generic/en-play-badge.png"
     alt="Get it on Google Play"
     height="80">](https://play.google.com/store/apps/details?id=com.froxot.cuscon)

Or download the latest APK from the [Releases Section](https://github.com/MiepHD/cuscon/releases/latest).

# Donate

https://www.buymeacoffee.com/yazazuyo

# Images

<img src="https://github.com/MiepHD/cuscon/assets/63968466/183ac3f3-c5a1-4d08-becb-658f0b69a74e" width="400" />
<img src="https://github.com/MiepHD/cuscon/assets/63968466/a2be67df-4dbd-40db-8e9d-cd597146a75d" width="400" />
<img src="https://github.com/MiepHD/cuscon/assets/63968466/9c2580ec-8704-4fe6-9dfd-024f668cba51" width="400" />
<img src="https://github.com/MiepHD/cuscon/assets/63968466/8ba07e70-6279-447e-a349-149fe25c831a" width="400" />
<img src="https://github.com/MiepHD/cuscon/assets/63968466/f433a4e0-fb98-44d0-b1c9-3a7a80deccf5" width="400" />
<img src="https://github.com/MiepHD/cuscon/assets/63968466/45310e7d-f102-450d-9c3f-391050e14dcc" width="400" />
<img src="https://github.com/MiepHD/cuscon/assets/63968466/17325662-5498-47d8-8e2c-a3e798455db0" width="400" />

# Requests

Please send requests to <a href="mailto:cuscon-requests@froxot.de">cuscon-requests@froxot.de</a> and donate something on [buymeacoffee.com](https://www.buymeacoffee.com/yazazuyo) or buy a premium request using the play store version

# Contributing

## Issues

<b>If you just want to create the images, please upload the request with edited images as an issue.</b>
For that you can follow the steps 1-4 under Pull Requests
(File types can be any images but SVG, WEBP, PNG is preferred)

## Pull Requests

Requirements:

- [Python](https://www.python.org/downloads/)

How-To:

1. If you want to contribute icons, you can uninstall your current version of cuscon and install [v4.0.1.7](https://github.com/MiepHD/cuscon/releases/tag/v4.0.1.7) to send an icon request to yourself (this is the last version that included the free request feature).
2. Extract the content of your request into `/requests/icon_request` so the images and XML files are directly in that folder.
3. From the `requests/` folder, run the new request manager:
   - `python manage_requests.py status` to show new icons, already added icons, conflicts, and missing metadata.
   - `python manage_requests.py resolve` to interactively resolve filename conflicts and manage request metadata.
   - `python manage_requests.py apply` to copy new drawables and append metadata into `app/src/main/res/xml/appfilter.xml`, `app/src/main/res/xml/drawable.xml`, and `app/src/main/res/xml/theme_resources.xml`.
4. If your request folder is not placed at `requests/icon_request`, use `python manage_requests.py --request-dir <path> status` instead.
5. Edit the icons so they match the contribution requirements.
6. Check the changelog/version details manually if needed before finalizing a release.
7. The `apply` command copies the selected icon files into `app/src/main/res/drawable-nodpi` and updates the XML files.
8. Review the generated git diff locally before creating a pull request.

# Requirements for contributing icons

- Icons must be outlined in black
- Icon should be visible on black background
- dimension of 512x512px
- should have approximate 30px transparent border
- The black border should be approximately 12px thick

# Background info

It always annoyed me that all apps are forced into the same rectangle. I searched for icon packs with transparent background but none did fit my idea. I wanted to preserve the beauty of the colors and style the designer of the app chose and not redesign the icon completely. That made me want to create my own icon pack exactly matching my vision. (I didn't think of doing it through applying every image myself as I already had in mind to share my pack with frineds.) I searched a lot on how to create my own icon pack but it felt very complex. So I started the icon pack as a modded version of an already existing icon pack. One day @LeHuman came over and told me that there exists a library called candybar. Now things got way easier even though it was my first time developing an android application. I first started publishing on Github, then added Google Play and finally F-Droid using candybar-foss. My first time publishing a real application too.

# License

The app is built with the **[CandyBar Dashboard](https://github.com/zixpo/candybar)** (and also with the **[FOSS version](https://github.com/Donnnno/candybar-foss)**) licensed under **[Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)**

The icons are licensed under **[Creative Commons BY-NC-ND License 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/)**

All files under `/store` and `/metadata` except `metadata/en-US/changelogs` are © Copyrighted by [@MiepHD](https://github.com/MiepHD) 2024-2025

