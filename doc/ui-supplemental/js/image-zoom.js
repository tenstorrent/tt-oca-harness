// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

'use strict'

;(function () {
  var images = document.querySelectorAll('.doc .imageblock .content > img')

  if (!images.length || typeof mediumZoom !== 'function') return

  var zoom = mediumZoom(images, {
    background: 'rgba(255, 255, 255, 0.96)',
    margin: 24
  })

  Array.prototype.forEach.call(images, function (image) {
    image.setAttribute('role', 'button')
    image.setAttribute('tabindex', '0')
    image.setAttribute('aria-label', (image.alt || 'Image') + ' (open enlarged view)')
    image.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter' && event.key !== ' ' &&
          event.key !== 'Spacebar' && event.keyCode !== 13 && event.keyCode !== 32) return

      event.preventDefault()
      zoom.open({ target: image })
    })
  })
})()
