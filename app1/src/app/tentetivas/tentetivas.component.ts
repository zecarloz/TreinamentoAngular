import { Component, OnInit } from '@angular/core';

@Component({
  selector: 'app-tentetivas',
  templateUrl: './tentetivas.component.html',
  styleUrls: ['./tentetivas.component.css']
})
export class TentetivasComponent implements OnInit {

  public coracaoVazio: string = '/assets/coracao_vazio.png'
  public coracaoCheio: string = '/assets/coracao_cheio.png'

  constructor() { }

  ngOnInit(): void {
  }

}
