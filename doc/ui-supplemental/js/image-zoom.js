// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

'use strict'

;(function () {
  var images = document.querySelectorAll('.doc .imageblock .content > img')

  if (!images.length || typeof Viewer !== 'function') return

  Array.prototype.forEach.call(images, function (image) {
    var viewer = new Viewer(image, {
      className: 'ocah-image-viewer',
      navbar: false,
      title: false,
      focus: false,
      rotatable: false,
      scalable: false,
      slideOnTouch: false,
      transition: false,
      toolbar: {
        zoomIn: true,
        zoomOut: true,
        oneToOne: function () { viewer.zoomTo(1) },
        reset: true
      },
      ready: function () {
        var labels = {
          'zoom-in': ['+', 'Zoom in'],
          'zoom-out': ['−', 'Zoom out'],
          'one-to-one': ['1:1', 'Actual size'],
          reset: ['Reset', 'Reset view']
        }
        var dialog = viewer.viewer
        Object.keys(labels).forEach(function (action) {
          var button = dialog.querySelector('.viewer-' + action)
          button.textContent = labels[action][0]
          button.setAttribute('aria-label', labels[action][1])
          button.setAttribute('title', labels[action][1])
        })
        viewer.button.setAttribute('aria-label', 'Close image viewer')
        viewer.button.setAttribute('title', 'Close (Esc)')
        dialog.addEventListener('keydown', function (event) {
          if ((event.key === ' ' || event.key === 'Enter') &&
              event.target.getAttribute('role') === 'button') {
            event.preventDefault()
            event.stopPropagation()
            event.target.click()
          }
          if (event.key === 'Tab') {
            var buttons = dialog.querySelectorAll('[role="button"][tabindex="0"]')
            var first = buttons[0]
            var last = buttons[buttons.length - 1]
            if (event.shiftKey && (event.target === first || event.target === dialog)) {
              event.preventDefault()
              last.focus()
            } else if (!event.shiftKey && event.target === last) {
              event.preventDefault()
              first.focus()
            }
          }
        })
      },
      shown: function () {
        viewer.viewer.removeAttribute('aria-labelledby')
        viewer.viewer.setAttribute('aria-label', image.alt || 'Image viewer')
        viewer.viewer.focus({ preventScroll: true })
      },
      hidden: function () {
        image.focus({ preventScroll: true })
      }
    })
    image.classList.add('image-zoomable')
    image.setAttribute('role', 'button')
    image.setAttribute('tabindex', '0')
    image.setAttribute('aria-haspopup', 'dialog')
    image.setAttribute('aria-label', (image.alt || 'Image') + ' (open enlarged view)')
    image.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter' && event.key !== ' ' &&
          event.key !== 'Spacebar' && event.keyCode !== 13 && event.keyCode !== 32) return

      event.preventDefault()
      viewer.show()
    })
  })
})()
