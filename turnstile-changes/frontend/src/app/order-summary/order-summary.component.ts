/*
 * Copyright (c) 2014-2026 Bjoern Kimminich & the OWASP Juice Shop contributors.
 * SPDX-License-Identifier: MIT
 */
import { environment } from '../../environments/environment'
import {
  Component,
  NgZone,
  type OnInit,
  type AfterViewInit,
  type OnDestroy,
  inject,
  ChangeDetectionStrategy,
  ElementRef,
  ViewChild
} from '@angular/core'
import { AddressService } from '../Services/address.service'
import { PaymentService } from '../Services/payment.service'
import { BasketService } from '../Services/basket.service'
import { Router } from '@angular/router'
import { DeliveryService } from '../Services/delivery.service'
import { SnackBarHelperService } from '../Services/snack-bar-helper.service'
import { MatIconModule } from '@angular/material/icon'
import { MatButtonModule } from '@angular/material/button'
import { PurchaseBasketComponent } from '../purchase-basket/purchase-basket.component'
import { TranslateModule } from '@ngx-translate/core'

import { MatCardModule } from '@angular/material/card'


declare global {
  interface Window {
    turnstile?: {
      render: (container: HTMLElement, options: any) => string
      remove: (widgetId: string) => void
      reset: (widgetId?: string) => void
    }
  }
}

function loadTurnstileScript (): Promise<void> {
  if (window.turnstile) {
    return Promise.resolve()
  }

  return new Promise((resolve, reject) => {
    let script = document.querySelector<HTMLScriptElement>(
      'script[data-cloudflare-turnstile]'
    )

    if (!script) {
      script = document.createElement('script')
      script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
      script.async = true
      script.defer = true
      script.dataset.cloudflareTurnstile = 'true'
    }

    script.addEventListener('load', () => {
      if (window.turnstile) {
        resolve()
      } else {
        reject(new Error('Cloudflare Turnstile failed to initialise'))
      }
    }, { once: true })

    script.addEventListener('error', () => {
      reject(new Error('Cloudflare Turnstile script failed to load'))
    }, { once: true })

    if (!script.isConnected) {
      document.head.appendChild(script)
    }
  })
}


@Component({
  changeDetection: ChangeDetectionStrategy.Eager,
  selector: 'app-order-summary',
  templateUrl: './order-summary.component.html',
  styleUrls: ['./order-summary.component.scss'],
  imports: [MatCardModule, TranslateModule, PurchaseBasketComponent, MatButtonModule, MatIconModule]
})
export class OrderSummaryComponent implements OnInit, AfterViewInit, OnDestroy {
  
  @ViewChild('turnstileContainer')
  private turnstileContainer!: ElementRef<HTMLElement>

  public turnstileToken: string | null = null

  private turnstileWidgetId?: string

  private readonly router = inject(Router)
  private readonly addressService = inject(AddressService)
  private readonly paymentService = inject(PaymentService)
  private readonly basketService = inject(BasketService)
  private readonly deliveryService = inject(DeliveryService)
  private readonly ngZone = inject(NgZone)
  private readonly snackBarHelperService = inject(SnackBarHelperService)

  public bonus = 0
  public itemTotal = 0
  public deliveryPrice = 0
  public promotionalDiscount = 0
  public address: any
  public paymentMethod: any

  ngOnInit (): void {
    this.deliveryService.getById(sessionStorage.getItem('deliveryMethodId')).subscribe((method) => {
      this.deliveryPrice = method.price
    })

    this.addressService.getById(sessionStorage.getItem('addressId')).subscribe({
      next: (address) => {
        this.address = address
      },
      error: (error) => { console.log(error) }
    })

    if (sessionStorage.getItem('paymentId') !== 'wallet') {
      this.paymentService.getById(sessionStorage.getItem('paymentId')).subscribe({
        next: (card) => {
          card.cardNum = String(card.cardNum).substring(String(card.cardNum).length - 4)
          this.paymentMethod = card
        },
        error: (err) => { console.log(err) }
      })
    } else if (sessionStorage.getItem('paymentId') === 'wallet') {
      this.paymentMethod = 'wallet'
    }
  }

  
  ngAfterViewInit (): void {
  	console.log('Order Summary: ngAfterViewInit called')
  	console.log('Turnstile Sitekey:', environment.turnstileSiteKey)

  	void this.initializeTurnstile()
  }

  ngOnDestroy (): void {
    if (this.turnstileWidgetId && window.turnstile) {
      window.turnstile.remove(this.turnstileWidgetId)
    }
  }

  private async initializeTurnstile (): Promise<void> {
    try {
      console.log('Turnstile initialisation started')

      await loadTurnstileScript()
      await loadTurnstileScript()

      if (!window.turnstile || !this.turnstileContainer) {
        throw new Error('Turnstile is not available')
      }

      this.turnstileWidgetId = window.turnstile.render(
        this.turnstileContainer.nativeElement,
        {
          sitekey: environment.turnstileSiteKey,
          callback: (token: string) => {
            this.ngZone.run(() => {
              this.turnstileToken = token
            })
          },
          action: 'checkout',
          'expired-callback': () => {
            this.ngZone.run(() => {
              this.turnstileToken = null
            })
          },
          'error-callback': () => {
            this.ngZone.run(() => {
              this.turnstileToken = null
            })
          }
        }
      )
    } catch (error) {
      console.error('Turnstile initialisation failed:', error)
      this.snackBarHelperService.open(
        'Could not load CAPTCHA verification. Please refresh the page.',
        'errorBar'
      )
    }
  }


  getMessage (total) {
    this.itemTotal = total[0]
    this.promotionalDiscount = sessionStorage.getItem('couponDiscount') ? (parseFloat(sessionStorage.getItem('couponDiscount')) / 100) * this.itemTotal : 0
    this.bonus = total[1]
  }

    placeOrder () {
    if (!this.turnstileToken) {
      this.snackBarHelperService.open(
        'Please complete the CAPTCHA verification.',
        'errorBar'
      )
      return
    }

    const orderDetails = {
      paymentId: sessionStorage.getItem('paymentId'),
      addressId: sessionStorage.getItem('addressId'),
      deliveryMethodId: sessionStorage.getItem('deliveryMethodId')
    }

    this.basketService.checkout(Number(sessionStorage.getItem('bid')),btoa(sessionStorage.getItem('couponDetails')),orderDetails,this.turnstileToken).subscribe({
      next: (orderConfirmationId) => {
        sessionStorage.removeItem('paymentId')
        sessionStorage.removeItem('addressId')
        sessionStorage.removeItem('deliveryMethodId')
        sessionStorage.removeItem('couponDetails')
        sessionStorage.removeItem('couponDiscount')
        this.basketService.updateNumberOfCartItems()
        this.ngZone.run(async () => await this.router.navigate(['/order-completion', orderConfirmationId]))
      },
    error: (err) => {
  	console.log(err)

  	this.turnstileToken = null

  	if (this.turnstileWidgetId && window.turnstile) {
    		window.turnstile.reset(this.turnstileWidgetId)
  	}

  	this.snackBarHelperService.open(
    		err.error?.error.message || 'Checkout failed. Please try again.',
    		'errorBar'
  	)
    }
    })
  }
}
