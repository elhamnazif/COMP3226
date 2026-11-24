from playwright.async_api import async_playwright
from playwright.async_api import expect

async def Login(email, pwd, page):
    """
    Login with the given email and password

    Args:
        email: Email to login with
        pwd: Password to login with
        page: Current website page. Will be verified is on correct page

    Returns:
        None
        At Products page (is verified)

    Raises:
        AssertionException:
        1. Login Button is not on current page (This is the page verification)
        2. Login was not successful
    """
    #Verification of current page is after getting fields

    #Login fields
    loginEmailF = page.get_by_label("Text field for the login email")
    loginPwdF = page.get_by_label("Text field for the login password")
    loginBtn = page.get_by_role('button', name="Login", exact=True)

    #Ensure we are on the login page
    await expect(loginBtn.first).to_be_visible()

    #Fill login
    await loginEmailF.fill(email)
    await loginPwdF.fill(pwd)
    await loginBtn.click()

    #Validate that login was successful AND gives time for page to load
    await expect(page.locator('app-product').first).to_be_visible()

async def Register(email, pwd, secQIx, secQAns, page, secQAttempts=2):
    """
    Register a new account with the given details

    Args:
        email: Email to register with. Does not need to be a legal email
        pwd: Password to register with
        secQIx: The security question to pick from [0-13] (for 14 total choices)
        secQAns: Answer to the security question but obviously does not need to be truthful
        secQAttempts: Number of times to try clicking the dropdown because sometimes it just doesnt do anything (defaults to 2)
        page: current website page

    Returns:
        None
        At login page (BUT not verified)

    Raises:
        ValueError:
        1. secQIx is not in [0-13]
        2. Login Button is not on current page (This is the page verification)
        3. Clicking the security question dropdown failed after sec attempts
    """
    #Verification of current page is after getting fields

    #Parameter validation
    if secQIx < 0 or secQIx > 13:
        raise ValueError(f"Security question index must be in [0-13]. Received {secQIx}")

    #Get needed fields
    emailF = page.get_by_label("Email address field")
    pwdF = page.get_by_label("Field for the password")
    pwdRepF = page.get_by_label("Field to confirm the password")
    secQDrop = page.locator('.mat-mdc-text-field-wrapper').nth(3) #Drop down field
    secQAnsF = page.get_by_label("Field for the answer to the security question")
    regBtn = page.get_by_role('button', name="Button to complete the registration")

    #Ensure we are on the register page
    await expect(regBtn.first).to_be_visible()

    #Fill in details
    await emailF.fill(email)
    await pwdF.fill(pwd)
    await pwdRepF.fill(pwd)
    for i in range(secQAttempts):
        try:
            await secQDrop.click()
            #Validate click worked AND gives time for dropdown to load
            await expect(page.get_by_role('listbox')).to_be_visible()
            break
        except AssertionError:
            #Try again since sometimes the 1st click just misses
            print(f"Potentially missed click {i+1}/{secQAttempts+1}. Trying again...")
    await page.get_by_role('option').nth(secQIx).click()
    await secQAnsF.fill(secQAns)
    
    await regBtn.click()

async def RegisterFromAcc(acc, page, secQAttempts = 2):
    """
    Register using Account class

    Args:
    acc: Account class
    page: current website page

    Has all the same properties as Register(email, pwd, secQIx, secQAns, page, secQAttempts=2)
    """
    await Register(acc.email, acc.pwd, acc.secQIndex, acc.secQAns, page, secQAttempts)

async def TraverseItems(do, page):
    """
    Traverse all products on the website

    Args:
    do: Function(item-pane,page) to do something given a product pane and the page. (The whole html element in juice-shop with tag <app-product>)
    page: current website page

    Returns:
    None
    At last Products page

    Raises:
    AssertionException:
    1. Cart Total indicator not visible (This is the page verification)
    2. Could not reach next page
    """

    nextButton = page.get_by_role('button', name="Next page")
    pageRange = page.locator('.mat-mdc-paginator-range-label').first

    await expect(pageRange).to_be_visible()

    curRange = await pageRange.inner_text()

    canNext = True #Keep cycling through pages while a next page exists
    nPages = 0 #Mostly for logging BUT also to prevent clicking next on the 1st page
    
    #Traversal to buy

    while(canNext):
        if(nPages > 0):
            await nextButton.click()
            await expect(pageRange).not_to_have_text(curRange, use_inner_text=True) #Check that we are on the next page

        products = await page.locator('app-product').all() #All product panes have the tag <app-product> so scrape by that

        for item in products:
            await do(item,page)

        canNext = not await nextButton.is_disabled()
        nPages = nPages + 1

        print(f"Done page {nPages}")

class Account():
    def __init__(self, e, p, si, sa, path="accounts.txt"):
        self.email = e
        self.pwd = p
        self.secQIndex = si
        self.secQAns = sa
        self.fPath = path

    def writeOut(self):
        with open(self.fPath, 'a') as f:
            f.write(str(self)+'\n')

    def __str__(self):
        return f"{self.email} | {self.pwd} | {self.secQIndex} | {self.secQAns}"