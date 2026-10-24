# Third-Party Software Notices & Acknowledgments

**FPS Patcher Studio** incorporates, bundles, or interfaces with the third-party open-source libraries, fonts, and utilities listed below. We gratefully acknowledge the authors and contributors of these projects.

---

## Table of Third-Party Components

| Component | Author / Maintainer | Primary License | Used For |
|---|---|---|---|
| [Python](https://www.python.org/) | Python Software Foundation | PSF License 2.0 | CPython 3.11 Runtime |
| [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) | Tom Schimansky | Creative Commons Zero v1.0 / MIT | Modern desktop UI framework |
| [TkinterDnD2](https://github.com/petasis/tkinterdnd2) | Georgios Petasis & Michael Lange | MIT License | Drag-and-drop file support |
| [pywinstyles](https://github.com/Akash-Bora/pywinstyles) | Akash Bora | MIT License | Windows 10/11 Acrylic, Mica & title bar theming |
| [Pillow](https://python-pillow.org/) | Alex Clark and Contributors | HPND License | Image loading, thumbnail resizing, icon processing |
| [Inter Font](https://rsms.me/inter/) | Rasmus Andersson | SIL Open Font License 1.1 | macOS HIG typography |
| [Inno Setup](https://jrsoftware.org/isinfo.php) | Jordan Russell and Martijn Laan | Inno Setup License (Modified BSD) | Windows installer compilation |
| [FFmpeg / FFprobe](https://ffmpeg.org/) | FFmpeg Developers | GNU LGPL v2.1+ / GPL v2.0+ | Optional video thumbnailing & metadata probing |
| [PyInstaller](https://pyinstaller.org/) | PyInstaller Development Team | GNU GPL v2.0 with Bootloader Exception | Standalone binary packaging |

---

## 1. Python (CPython)

- **Website**: https://www.python.org/
- **License**: Python Software Foundation License Version 2.0

```text
PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2
--------------------------------------------
1. This LICENSE AGREEMENT is between the Python Software Foundation ("PSF"), and
   the Individual or Organization ("Licensee") accessing and otherwise using this
   software ("Python") in source or binary form and its associated documentation.

2. Subject to the terms and conditions of this License Agreement, PSF hereby
   grants Licensee a nonexclusive, royalty-free, world-wide license to reproduce,
   analyze, test, perform and/or display publicly, prepare derivative works,
   distribute, and otherwise use Python alone or in any derivative version,
   provided, however, that PSF's License Agreement and PSF's notice of copyright,
   i.e., "Copyright © 2001-2026 Python Software Foundation; All Rights Reserved"
   are retained in Python alone or in any derivative version prepared by Licensee.

3. In the event Licensee prepares a derivative work that is based on or
   incorporates Python or any part thereof, and wants to make the derivative work
   available to others as provided herein, then Licensee hereby agrees to include
   in any such work a brief summary of the changes made to Python.

4. PSF is making Python available to Licensee on an "AS IS" basis. PSF MAKES NO
   REPRESENTATIONS OR WARRANTIES, EXPRESS OR IMPLIED. BY WAY OF EXAMPLE, BUT NOT
   LIMITATION, PSF MAKES NO AND DISCLAIMS ANY REPRESENTATION OR WARRANTY OF
   MERCHANTABILITY OR FITNESS FOR ANY PARTICULAR PURPOSE OR THAT THE USE OF
   PYTHON WILL NOT INFRINGE ANY THIRD PARTY RIGHTS.

5. PSF SHALL NOT BE LIABLE TO LICENSEE OR ANY OTHER USERS OF PYTHON FOR ANY
   INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES OR LOSS AS A RESULT OF MODIFYING,
   DISTRIBUTING, OR OTHERWISE USING PYTHON, OR ANY DERIVATIVE THEREOF, EVEN IF
   ADVISED OF THE POSSIBILITY THEREOF.
```

---

## 2. CustomTkinter

- **Author**: Tom Schimansky
- **Website**: https://github.com/TomSchimansky/CustomTkinter
- **License**: Creative Commons Zero v1.0 Universal / MIT License

```text
MIT License

Copyright (c) 2023 Tom Schimansky

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 3. TkinterDnD2

- **Author**: Georgios Petasis, Michael Lange
- **Website**: https://github.com/petasis/tkinterdnd2
- **License**: MIT License

```text
Copyright (c) 2010-2020 Georgios Petasis
Copyright (c) 2007-2009 Michael Lange

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 4. pywinstyles

- **Author**: Akash Bora
- **Website**: https://github.com/Akash-Bora/pywinstyles
- **License**: MIT License

```text
Copyright (c) 2023-2024 Akash Bora

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 5. Pillow (PIL Fork)

- **Author**: Alex Clark and Contributors (originally Fredrik Lundh and Contributors)
- **Website**: https://python-pillow.org/
- **License**: HPND License (Historical Permission Notice and Disclaimer)

```text
The Python Imaging Library (PIL) is

    Copyright © 1997-2011 by Secret Labs AB
    Copyright © 1995-2011 by Fredrik Lundh

Pillow is the friendly PIL fork. It is

    Copyright © 2010-2026 by Alex Clark and contributors

Like PIL, Pillow is licensed under the open source HPND License:

By obtaining, using, and/or copying this software and/or its associated
documentation, you agree that you have read, understood, and will comply
with the following terms and conditions:

Permission to use, copy, modify, and distribute this software and its
associated documentation for any purpose and without fee is hereby granted,
provided that the above copyright notice appears in all copies, and that
both that copyright notice and this permission notice appear in supporting
documentation, and that the name of Secret Labs AB or the author not be
used in advertising or publicity pertaining to distribution of the software
without specific, written prior permission.

SECRET LABS AB AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS
SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS.
IN NO EVENT SHALL SECRET LABS AB OR THE AUTHOR BE LIABLE FOR ANY SPECIAL,
INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE
OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE.
```

---

## 6. Inter Font Family

- **Author**: Rasmus Andersson
- **Website**: https://rsms.me/inter/
- **License**: SIL Open Font License, Version 1.1

```text
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007

Copyright (c) 2016-2024 The Inter Project Authors (https://github.com/rsms/inter)

Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless prominent written permission is granted by the
corresponding Copyright Holder. This restriction only applies to the
primary font name as presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
```

---

## 7. Inno Setup

- **Author**: Jordan Russell, Martijn Laan
- **Website**: https://jrsoftware.org/
- **License**: Inno Setup License (Modified BSD)

```text
Inno Setup License
==================

Except where otherwise noted, all of the documentation and software included
in the Inno Setup package is copyrighted by Jordan Russell.

Copyright (C) 1997-2026 Jordan Russell. All rights reserved.
Portions Copyright (C) 2000-2026 Martijn Laan

This software is provided "as-is," without any express or implied warranty.
In no event shall the author be held liable for any damages arising from the
use of this software.

Permission is granted to anyone to use this software for any purpose, including
commercial applications, and to alter and redistribute it, provided that the
following conditions are met:

1. All redistributions of source code must retain the above copyright notice,
   this list of conditions, and the following disclaimer.

2. All redistributions in binary form must reproduce the above copyright
   notice, this list of conditions, and the following disclaimer in the
   documentation and/or other materials provided with the distribution.

3. The origin of this software must not be misrepresented; you must not claim
   that you wrote the original software. If you use this software in a product,
   an acknowledgment in the product documentation would be appreciated but is
   not required.
```

---

## 8. FFmpeg & FFprobe (LGPL v2.1 / GPL v2.0 Compliance Notice)

- **Website**: https://ffmpeg.org/
- **License**: GNU Lesser General Public License (LGPL) version 2.1 or later / GNU General Public License (GPL) version 2.0 or later (depending on the build configuration of FFmpeg used).

### Compliance & Separation Notice:
1. **Dynamic / Subprocess Invocation**: FPS Patcher Studio **does not bundle, statically link, or dynamically link** against FFmpeg shared libraries (`avcodec`, `avformat`, `avutil`, etc.).
2. **Independent Executable**: Any interaction with FFmpeg is performed purely via standard operating system subprocess execution (`subprocess.Popen`) calling the standalone CLI tools `ffmpeg.exe` or `ffprobe.exe`.
3. **Optional Dependency**: FPS Patcher Studio does not require FFmpeg for core MP4/MOV container timing patch operations (which are performed by our pure-Python atom engine). FFmpeg is utilized strictly for optional video thumbnail extraction and fallback stream inspection.
4. **Acquisition & Source Code**: Users can supply their own FFmpeg binaries, locate existing system PATH binaries, or trigger the built-in auto-downloader to fetch pre-compiled builds provided by third-party build distributors (e.g., Gyan.dev or BtbN). Source code for FFmpeg is available at [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html).

---

## 9. PyInstaller

- **Author**: PyInstaller Development Team
- **Website**: https://pyinstaller.org/
- **License**: GNU General Public License v2.0 with the **PyInstaller Bootloader Exception**

```text
The PyInstaller bootloader is licensed under the GNU General Public License (GPL)
version 2, with the following special exception:

Bootloader Exception:
In addition to the permissions in the GNU General Public License, the authors
give you unlimited permission to link or combine the compiled bootloader with
independent modules that communicate with the bootloader solely through the
standard C, Python, or operating system interfaces. You may copy and distribute
the resulting combined executable under terms of your choice, provided that
every copy of the combined executable is accompanied by a complete copy of
the source code of the bootloader.
```
*Because of this exception, distributing FPS Patcher Studio under the MIT License is fully permissible.*
