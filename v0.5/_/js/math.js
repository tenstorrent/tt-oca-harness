// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

'use strict'

;(function () {
  var article = document.querySelector('.doc')
  if (!article) return

  window.MathJax = {
    startup: { elements: [article] },
    tex: {
      packages: ['base', 'ams', 'newcommand', 'configmacros', 'noundefined'],
      inlineMath: [['\\(', '\\)']],
      displayMath: [['\\[', '\\]']]
    },
    options: { enableMenu: false }
  }
})()
