import { MeuAppPage } from './app.po';

describe('meu-app App', function() {
  let page: MeuAppPage;

  beforeEach(() => {
    page = new MeuAppPage();
  });

  it('should display message saying app works', () => {
    page.navigateTo();
    expect(page.getParagraphText()).toEqual('app works!');
  });
});
